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
)


class DummyOut(BaseModel):
    answer: str
    score: int


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
# ---------------------------------------------------------------------------

def test_for_scoring_uses_scoring_env_when_set(monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_SCORING_MODEL", "gpt-5.1-mini")
    monkeypatch.setenv("BEWERBER_GENERATION_MODEL", "gpt-5.1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("OPENAI_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("BEWERBER_LLM_MODEL", raising=False)
    mocker.patch("bewerber.shared.llm.OpenAI")

    scoring = LLMClient.for_scoring()
    generation = LLMClient.for_generation()
    assert scoring.model == "gpt-5.1-mini"
    assert generation.model == "gpt-5.1"


def test_role_env_falls_back_to_llm_model_env(monkeypatch, mocker):
    """Wenn role-spezifisches env fehlt, greift BEWERBER_LLM_MODEL."""
    monkeypatch.delenv("BEWERBER_SCORING_MODEL", raising=False)
    monkeypatch.delenv("BEWERBER_GENERATION_MODEL", raising=False)
    monkeypatch.setenv("BEWERBER_LLM_MODEL", "gpt-5.1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("OPENAI_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mocker.patch("bewerber.shared.llm.OpenAI")

    assert LLMClient.for_scoring().model == "gpt-5.1"
    assert LLMClient.for_generation().model == "gpt-5.1"


def test_role_env_falls_back_to_default_when_nothing_set(monkeypatch, mocker):
    monkeypatch.delenv("BEWERBER_SCORING_MODEL", raising=False)
    monkeypatch.delenv("BEWERBER_GENERATION_MODEL", raising=False)
    monkeypatch.delenv("BEWERBER_LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("OPENAI_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mocker.patch("bewerber.shared.llm.OpenAI")

    assert LLMClient.for_scoring().model == LLMClient.DEFAULT_MODEL
    assert LLMClient.for_generation().model == LLMClient.DEFAULT_MODEL


def test_role_env_overrides_legacy_llm_model_env(monkeypatch, mocker):
    """Role-spezifisches env hat Vorrang vor BEWERBER_LLM_MODEL."""
    monkeypatch.setenv("BEWERBER_LLM_MODEL", "gpt-5.1")
    monkeypatch.setenv("BEWERBER_SCORING_MODEL", "gpt-5.1-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("OPENAI_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mocker.patch("bewerber.shared.llm.OpenAI")

    assert LLMClient.for_scoring().model == "gpt-5.1-mini"
    # Generation faellt auf LLM_MODEL zurueck
    assert LLMClient.for_generation().model == "gpt-5.1"


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
