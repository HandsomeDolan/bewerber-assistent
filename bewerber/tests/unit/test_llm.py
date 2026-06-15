import httpx
import pytest
from openai import RateLimitError
from pydantic import BaseModel

from bewerber.shared.llm import (
    LLMAllProvidersFailed,
    LLMClient,
    LLMQuotaExhausted,
    LLMTransientError,
    OpenAIProvider,
    _sanitize_schema_for_gemini,
)


class DummyOut(BaseModel):
    answer: str
    score: int


# ---------------------------------------------------------------------------
# Gemini schema sanitizer
# ---------------------------------------------------------------------------

def test_sanitize_strips_additional_properties_at_root():
    schema = {"type": "object", "additionalProperties": False, "properties": {}}
    out = _sanitize_schema_for_gemini(schema)
    assert "additionalProperties" not in out
    assert out["type"] == "object"


def test_sanitize_strips_title_and_default():
    schema = {
        "type": "object",
        "title": "Scoring",
        "default": {},
        "properties": {
            "x": {"type": "integer", "title": "X", "default": 0, "minimum": 1},
        },
    }
    out = _sanitize_schema_for_gemini(schema)
    assert "title" not in out
    assert "default" not in out
    assert "title" not in out["properties"]["x"]
    assert "default" not in out["properties"]["x"]
    # Allowed fields must remain
    assert out["properties"]["x"]["minimum"] == 1


def test_sanitize_recurses_into_nested_arrays_and_dicts():
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {"type": "string", "title": "Skill"},
                },
            },
        },
    }
    out = _sanitize_schema_for_gemini(schema)
    assert "additionalProperties" not in out["items"]
    assert "title" not in out["items"]["properties"]["skills"]["items"]


def test_sanitize_actual_scoring_schema_has_no_unsupported_keys():
    """End-to-end: das echte Scoring-Pydantic-Schema produziert nach
    Sanitize keinen verbotenen Key mehr."""
    from bewerber.shared.state_schema import Scoring
    sanitized = _sanitize_schema_for_gemini(Scoring.model_json_schema())

    def walk(node):
        if isinstance(node, dict):
            for k in node:
                assert k not in {"additionalProperties", "title", "$defs", "default"}
                walk(node[k])
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(sanitized)


# ---------------------------------------------------------------------------
# Backward-compat tests: LLMClient(client=fake, model=...) preserved
# ---------------------------------------------------------------------------

def test_structured_call_uses_responses_parse(mocker):
    fake_client = mocker.Mock()
    fake_resp = mocker.Mock()
    fake_resp.output_parsed = DummyOut(answer="hello", score=7)
    fake_client.responses.parse.return_value = fake_resp

    client = LLMClient(client=fake_client, model="gpt-test")
    result = client.structured(system="be helpful", user="hi", schema=DummyOut)

    assert result.answer == "hello"
    assert result.score == 7
    fake_client.responses.parse.assert_called_once()
    call_kwargs = fake_client.responses.parse.call_args.kwargs
    assert call_kwargs["model"] == "gpt-test"
    assert call_kwargs["text_format"] == DummyOut


def test_text_call(mocker):
    fake_client = mocker.Mock()
    fake_resp = mocker.Mock()
    fake_resp.output_text = "plain answer"
    fake_client.responses.create.return_value = fake_resp

    client = LLMClient(client=fake_client, model="gpt-test")
    assert client.text(system="s", user="u") == "plain answer"


def test_default_model_from_env(monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_LLM_MODEL", "gpt-from-env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("OPENAI_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mocker.patch("bewerber.shared.llm.OpenAI")

    client = LLMClient()
    assert client.model == "gpt-from-env"
    assert len(client.providers) == 1


# ---------------------------------------------------------------------------
# Helpers to fabricate real openai RateLimitError variants
# ---------------------------------------------------------------------------

def _openai_quota_error() -> RateLimitError:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(429, request=req)
    return RateLimitError(
        message="quota",
        response=resp,
        body={"error": {"code": "insufficient_quota", "message": "out of quota"}},
    )


def _openai_rate_burst_error() -> RateLimitError:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(429, request=req)
    return RateLimitError(
        message="burst",
        response=resp,
        body={"error": {"code": "rate_limit_exceeded", "message": "tpm exceeded"}},
    )


# ---------------------------------------------------------------------------
# OpenAIProvider classifies RateLimitError correctly
# ---------------------------------------------------------------------------

def test_openai_provider_insufficient_quota_raises_quota_exhausted(mocker):
    fake = mocker.Mock()
    fake.responses.create.side_effect = _openai_quota_error()

    p = OpenAIProvider(client=fake, model="m")
    with pytest.raises(LLMQuotaExhausted):
        p.text(system="s", user="u")


def test_openai_provider_rate_burst_raises_transient(mocker):
    fake = mocker.Mock()
    fake.responses.create.side_effect = _openai_rate_burst_error()

    p = OpenAIProvider(client=fake, model="m")
    with pytest.raises(LLMTransientError):
        p.text(system="s", user="u")


# ---------------------------------------------------------------------------
# LLMClient chain semantics
# ---------------------------------------------------------------------------

def _stub_provider(mocker, name="stub", model="m"):
    p = mocker.Mock(spec=["structured", "text", "model", "name"])
    p.model = model
    p.name = name
    return p


def test_fallback_on_quota_exhausted(mocker):
    """Primary quota gone → fallback called → success."""
    primary = _stub_provider(mocker, name="p1")
    primary.structured.side_effect = LLMQuotaExhausted("p1 out")
    fallback = _stub_provider(mocker, name="p2")
    fallback.structured.return_value = DummyOut(answer="fb", score=1)

    client = LLMClient(providers=[primary, fallback])
    out = client.structured(system="s", user="u", schema=DummyOut)

    assert out.answer == "fb"
    primary.structured.assert_called_once()
    fallback.structured.assert_called_once()


def test_retry_then_succeed_on_transient(mocker, monkeypatch):
    """Single provider: transient on first call → 1 retry → succeeds."""
    monkeypatch.setattr(LLMClient, "RETRY_DELAY_S", 0)
    p = _stub_provider(mocker)
    p.text.side_effect = [LLMTransientError("burst"), "OK"]

    client = LLMClient(providers=[p])
    assert client.text(system="s", user="u") == "OK"
    assert p.text.call_count == 2


def test_fallback_when_retry_also_fails(mocker, monkeypatch):
    """Transient persists on retry → next provider tried."""
    monkeypatch.setattr(LLMClient, "RETRY_DELAY_S", 0)
    primary = _stub_provider(mocker, name="p1")
    primary.text.side_effect = LLMTransientError("persistent 5xx")
    fallback = _stub_provider(mocker, name="p2")
    fallback.text.return_value = "from fallback"

    client = LLMClient(providers=[primary, fallback])
    assert client.text(system="s", user="u") == "from fallback"
    assert primary.text.call_count == 2  # initial + 1 retry
    fallback.text.assert_called_once()


def test_all_providers_fail_raises(mocker, monkeypatch):
    monkeypatch.setattr(LLMClient, "RETRY_DELAY_S", 0)
    p1 = _stub_provider(mocker, name="p1")
    p1.text.side_effect = LLMQuotaExhausted("p1")
    p2 = _stub_provider(mocker, name="p2")
    p2.text.side_effect = LLMQuotaExhausted("p2")

    client = LLMClient(providers=[p1, p2])
    with pytest.raises(LLMAllProvidersFailed):
        client.text(system="s", user="u")


def test_non_retryable_error_propagates(mocker):
    """Bad-request / 4xx (other than quota / rate-limit) shouldn't trigger fallback."""
    primary = _stub_provider(mocker, name="p1")
    primary.text.side_effect = ValueError("bad request")
    fallback = _stub_provider(mocker, name="p2")
    fallback.text.return_value = "fb"

    client = LLMClient(providers=[primary, fallback])
    with pytest.raises(ValueError):
        client.text(system="s", user="u")
    fallback.text.assert_not_called()


# ---------------------------------------------------------------------------
# Default-chain construction from env
# ---------------------------------------------------------------------------

def test_chain_skips_fallbacks_when_no_keys(monkeypatch, mocker):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("OPENAI_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mocker.patch("bewerber.shared.llm.OpenAI")

    client = LLMClient()
    assert len(client.providers) == 1


def test_chain_includes_openai_fallback_when_key_set(monkeypatch, mocker):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_API_KEY_FALLBACK", "sk-fake-2")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mocker.patch("bewerber.shared.llm.OpenAI")

    client = LLMClient()
    assert len(client.providers) == 2
    assert all("openai:" in p.name for p in client.providers)


# ---------------------------------------------------------------------------
# Role-specific factories: for_scoring / for_generation
# Tests die Provider-Order-Konfiguration + per-Provider-Models.
# ---------------------------------------------------------------------------

def _clean_env(monkeypatch):
    """Reset alle bewerber-LLM-Envs auf einen sauberen Default."""
    for var in [
        "BEWERBER_SCORING_PROVIDER_ORDER",
        "BEWERBER_GENERATION_PROVIDER_ORDER",
        "BEWERBER_SCORING_OPENAI_MODEL",
        "BEWERBER_SCORING_GEMINI_MODEL",
        "BEWERBER_GENERATION_OPENAI_MODEL",
        "BEWERBER_GENERATION_GEMINI_MODEL",
        "BEWERBER_LLM_MODEL",
        "BEWERBER_GEMINI_MODEL",
        "OPENAI_API_KEY_FALLBACK",
        "GOOGLE_API_KEY",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


def test_default_provider_order_is_openai_then_gemini(monkeypatch, mocker):
    """Default: OpenAI primary, Gemini Fallback."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIz-fake")
    mocker.patch("bewerber.shared.llm.OpenAI")
    mocker.patch("bewerber.shared.llm.GeminiProvider")  # avoid real construction

    client = LLMClient.for_scoring()
    names = [p.name if not hasattr(p, "_mock_name") else "gemini" for p in client.providers]
    assert names[0].startswith("openai:"), f"got {names!r}"
    assert "gemini" in str(names[-1]).lower()


def test_provider_order_can_be_flipped_to_gemini_first(monkeypatch, mocker):
    """BEWERBER_SCORING_PROVIDER_ORDER='gemini,openai' -> Gemini wird primary."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("BEWERBER_SCORING_PROVIDER_ORDER", "gemini,openai")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIz-fake")
    mocker.patch("bewerber.shared.llm.OpenAI")
    fake_gemini = mocker.patch("bewerber.shared.llm.GeminiProvider")
    fake_gemini.return_value.model = "gemini-2.0-flash-exp"
    fake_gemini.return_value.name = "gemini:gemini-2.0-flash-exp"

    client = LLMClient.for_scoring()
    # First provider should be Gemini
    assert "gemini" in client.providers[0].name.lower()
    # Second is OpenAI primary
    assert client.providers[1].name.startswith("openai:")


def test_each_provider_gets_its_own_model(monkeypatch, mocker):
    """OpenAI bekommt OPENAI_MODEL, Gemini bekommt GEMINI_MODEL - NICHT denselben Namen."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("BEWERBER_SCORING_OPENAI_MODEL", "gpt-5.1-mini")
    monkeypatch.setenv("BEWERBER_SCORING_GEMINI_MODEL", "gemini-2.0-flash-exp")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIz-fake")
    mocker.patch("bewerber.shared.llm.OpenAI")
    fake_gemini = mocker.patch("bewerber.shared.llm.GeminiProvider")
    fake_gemini.return_value.model = "gemini-2.0-flash-exp"
    fake_gemini.return_value.name = "gemini:gemini-2.0-flash-exp"

    client = LLMClient.for_scoring()
    # OpenAI provider model
    openai_p = next(p for p in client.providers if p.name.startswith("openai:"))
    assert openai_p.model == "gpt-5.1-mini"
    # Gemini provider got the OTHER model
    assert fake_gemini.call_args.kwargs["model"] == "gemini-2.0-flash-exp"


def test_unknown_provider_in_order_is_skipped_with_warning(monkeypatch, mocker, caplog):
    _clean_env(monkeypatch)
    monkeypatch.setenv("BEWERBER_SCORING_PROVIDER_ORDER", "openai,whatever,gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIz-fake")
    mocker.patch("bewerber.shared.llm.OpenAI")
    mocker.patch("bewerber.shared.llm.GeminiProvider")

    import logging
    with caplog.at_level(logging.WARNING):
        client = LLMClient.for_scoring()
    # 2 valid providers (openai primary + gemini)
    assert len(client.providers) == 2
    assert "Unbekannter Provider 'whatever'" in caplog.text


def test_role_specific_envs_take_precedence_over_legacy(monkeypatch, mocker):
    """SCORING_OPENAI_MODEL > BEWERBER_LLM_MODEL."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("BEWERBER_LLM_MODEL", "gpt-5.1")
    monkeypatch.setenv("BEWERBER_SCORING_OPENAI_MODEL", "gpt-5.1-mini")
    mocker.patch("bewerber.shared.llm.OpenAI")

    scoring = LLMClient.for_scoring()
    # Scoring uses the SCORING-specific override
    assert scoring.providers[0].model == "gpt-5.1-mini"
    # Generation falls back to BEWERBER_LLM_MODEL
    generation = LLMClient.for_generation()
    assert generation.providers[0].model == "gpt-5.1"


def test_openai_provider_skipped_when_no_api_key(monkeypatch, mocker):
    """Ohne OPENAI_API_KEY -> kein OpenAI-Provider in der Chain (statt Crash)."""
    _clean_env(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIz-fake")
    mocker.patch("bewerber.shared.llm.OpenAI")
    fake_gemini = mocker.patch("bewerber.shared.llm.GeminiProvider")
    fake_gemini.return_value.model = "gemini-2.0-flash-exp"
    fake_gemini.return_value.name = "gemini:gemini-2.0-flash-exp"

    client = LLMClient.for_scoring()
    # Only Gemini in the chain
    assert all("openai" not in p.name for p in client.providers)
    assert len(client.providers) == 1


def test_gemini_provider_skipped_when_no_google_key(monkeypatch, mocker):
    """Ohne GOOGLE_API_KEY -> kein Gemini-Provider (auch wenn in Order)."""
    _clean_env(monkeypatch)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mocker.patch("bewerber.shared.llm.OpenAI")
    mocker.patch("bewerber.shared.llm.GeminiProvider")

    client = LLMClient.for_scoring()
    # Only OpenAI primary
    assert len(client.providers) == 1
    assert client.providers[0].name.startswith("openai:")


def test_chain_includes_gemini_when_google_key_set(monkeypatch, mocker):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("OPENAI_API_KEY_FALLBACK", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIz-fake")
    mocker.patch("bewerber.shared.llm.OpenAI")

    # Patch the genai.Client used inside GeminiProvider constructor
    mock_genai_module = mocker.MagicMock()
    mocker.patch.dict("sys.modules", {"google.genai": mock_genai_module})
    # Re-import path: bewerber.shared.llm imports `from google import genai` lazily
    mock_google_genai = mocker.MagicMock()
    mock_google_genai.genai = mock_genai_module
    mocker.patch.dict("sys.modules", {"google": mock_google_genai})

    client = LLMClient()
    # OpenAI primary + Gemini fallback
    assert len(client.providers) == 2
    assert client.providers[0].name.startswith("openai:")
    assert client.providers[1].name.startswith("gemini:")
