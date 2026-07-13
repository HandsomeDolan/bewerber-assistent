"""LLM client with multi-provider fallback chain.

Default chain (in order):
  1. OpenAI primary  - OPENAI_API_KEY,          model = BEWERBER_LLM_MODEL or 'gpt-5-mini'
  2. OpenAI fallback - OPENAI_API_KEY_FALLBACK, same model        (skipped if env unset)
  3. Google Gemini   - GOOGLE_API_KEY,          model = BEWERBER_GEMINI_MODEL or
                                                        'gemini-2.0-flash-exp' (skipped if unset)

Error handling per call:
  - insufficient_quota (429 quota gone)  -> immediately try next provider
  - rate_limit_exceeded / 5xx / network  -> one retry on same provider with 1.5s backoff;
                                            if it persists, try next provider
  - non-retryable error                  -> propagated unchanged

Backward compatibility: LLMClient(client=X, model=Y) still works and produces a
single-provider chain wrapping the injected OpenAI client.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Type, TypeVar

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)

# Harter HTTP-Timeout fuer alle selbstgebauten Provider-Clients. Ohne ihn
# uebergibt google-genai timeout=None an httpx (haengt unbegrenzt in ssl.read,
# Incident 2026-07-13); der OpenAI-SDK-Default waere 600s.
DEFAULT_TIMEOUT_S = 120.0


def _timeout_s() -> float:
    raw = os.environ.get("BEWERBER_LLM_TIMEOUT_S", "")
    try:
        return float(raw) if raw else DEFAULT_TIMEOUT_S
    except ValueError:
        log.warning("[LLM] BEWERBER_LLM_TIMEOUT_S=%r ungueltig - nutze %ss", raw, DEFAULT_TIMEOUT_S)
        return DEFAULT_TIMEOUT_S


_GEMINI_DROP_KEYS = frozenset({
    # Gemini's response_schema lehnt diese ab, obwohl pydantic sie emittiert:
    "additionalProperties",  # aus extra='forbid'
    "title",                 # pydantic schreibt fuer jedes Feld eines
    "default",
    "$defs",
    "$ref",                  # Refs MUESSEN inlined sein (pydantic v2 tut das
                             # in der Regel - falls nicht, schlaegt es spaeter
                             # mit einer klareren Meldung fehl)
    "examples",
    "discriminator",
    "patternProperties",
})


def _sanitize_schema_for_gemini(node: Any) -> Any:
    """Recursively strip JSON Schema keys that Gemini's response_schema doesn't accept.

    Operates on the dict returned by `model.model_json_schema()`. Leaves
    types/structure alone; nur einzelne Keys werden gedroppt.
    """
    if isinstance(node, dict):
        return {
            k: _sanitize_schema_for_gemini(v)
            for k, v in node.items()
            if k not in _GEMINI_DROP_KEYS
        }
    if isinstance(node, list):
        return [_sanitize_schema_for_gemini(item) for item in node]
    return node


class LLMQuotaExhausted(Exception):
    """Provider's quota is gone. Move on to the next provider."""


class LLMTransientError(Exception):
    """Rate-limit burst / 5xx / connection blip. Retryable; one retry; then next provider."""


class LLMAllProvidersFailed(Exception):
    """Every provider in the chain failed."""


class _Provider:
    """Provider interface. Implementations must raise LLMQuotaExhausted /
    LLMTransientError for the two cases the fallback layer cares about."""

    name: str
    model: str

    def structured(self, *, system: str, user: str, schema: Type[T]) -> T:
        raise NotImplementedError

    def text(self, *, system: str, user: str) -> str:
        raise NotImplementedError


class OpenAIProvider(_Provider):
    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        api_key: str | None = None,
        model: str,
    ) -> None:
        if client is not None:
            self.client = client
        elif api_key:
            self.client = OpenAI(api_key=api_key, timeout=_timeout_s())
        else:
            self.client = OpenAI(timeout=_timeout_s())
        self.model = model
        self.name = f"openai:{model}"

    def structured(self, *, system: str, user: str, schema: Type[T]) -> T:
        try:
            resp = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                text_format=schema,
            )
            return resp.output_parsed
        except RateLimitError as e:
            self._raise_classified(e)
        except (InternalServerError, APIConnectionError) as e:
            raise LLMTransientError(f"{self.name}: {e}") from e
        except APIStatusError as e:
            if 500 <= e.status_code < 600:
                raise LLMTransientError(f"{self.name}: {e}") from e
            raise

    def text(self, *, system: str, user: str) -> str:
        try:
            resp = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.output_text
        except RateLimitError as e:
            self._raise_classified(e)
        except (InternalServerError, APIConnectionError) as e:
            raise LLMTransientError(f"{self.name}: {e}") from e
        except APIStatusError as e:
            if 500 <= e.status_code < 600:
                raise LLMTransientError(f"{self.name}: {e}") from e
            raise

    def _raise_classified(self, e: RateLimitError) -> None:
        body = e.body if isinstance(e.body, dict) else {}
        code = (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None
        if code == "insufficient_quota":
            raise LLMQuotaExhausted(f"{self.name}: {e}") from e
        raise LLMTransientError(f"{self.name}: {e}") from e


class GeminiProvider(_Provider):
    """Google Gemini provider via the `google-genai` SDK.

    Structured outputs werden als sanitized JSON Schema uebergeben (nicht
    direkt die Pydantic-Klasse): pydantic emittiert `additionalProperties`
    + `title` ueberall (durch `extra='forbid'`), die Gemini-API lehnt das
    als INVALID_ARGUMENT ab. _sanitize_schema_for_gemini() entfernt diese
    Felder rekursiv. Falls trotzdem ein Schema-Fehler kommt, faellt der
    Code auf reine JSON-Mode-Ausgabe zurueck und parst mit Pydantic.
    """

    def __init__(self, *, api_key: str | None = None, model: str, client: Any = None) -> None:
        # Lazy import: only load google-genai when this provider is actually constructed
        from google import genai  # noqa: WPS433
        self.model = model
        # http_options.timeout ist in MILLISEKUNDEN; ohne ihn gibt das SDK
        # timeout=None an httpx weiter (= kein Timeout, ewiger ssl.read).
        self.client = client or genai.Client(
            api_key=api_key or os.environ.get("GOOGLE_API_KEY"),
            http_options={"timeout": int(_timeout_s() * 1000)},
        )
        self.name = f"gemini:{model}"

    def structured(self, *, system: str, user: str, schema: Type[T]) -> T:
        from google.genai import errors as gerrors  # noqa: WPS433
        from google.genai import types as gtypes  # noqa: WPS433
        sanitized = _sanitize_schema_for_gemini(schema.model_json_schema())
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=gtypes.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=sanitized,
                ),
            )
        except gerrors.ClientError as e:
            self._raise_classified(e)
        except gerrors.ServerError as e:
            raise LLMTransientError(f"{self.name}: {e}") from e
        except httpx.TransportError as e:
            # Timeout / Netzwerkfehler unterhalb der genai-Fehlerklassen
            raise LLMTransientError(f"{self.name}: {e}") from e
        # Wir haben ein dict-Schema uebergeben, also liefert resp.parsed ein
        # dict (kein Pydantic-Objekt). Immer ueber den expliziten Validator.
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        if isinstance(parsed, dict):
            return schema.model_validate(parsed)
        return schema.model_validate_json(resp.text)

    def text(self, *, system: str, user: str) -> str:
        from google.genai import errors as gerrors  # noqa: WPS433
        from google.genai import types as gtypes  # noqa: WPS433
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=gtypes.GenerateContentConfig(system_instruction=system),
            )
        except gerrors.ClientError as e:
            self._raise_classified(e)
        except gerrors.ServerError as e:
            raise LLMTransientError(f"{self.name}: {e}") from e
        except httpx.TransportError as e:
            raise LLMTransientError(f"{self.name}: {e}") from e
        return resp.text or ""

    def _raise_classified(self, e: Any) -> None:
        # google.genai.errors.ClientError has .code (HTTP) and .status (string)
        status = getattr(e, "status", "") or ""
        if status == "RESOURCE_EXHAUSTED":
            raise LLMQuotaExhausted(f"{self.name}: {e}") from e
        # Other 4xx (auth, bad request) shouldn't fall back blindly to next provider
        raise


class LLMClient:
    """Multi-provider LLM client with quota-fallback + transient retry.

    Two role-specific factory methods (`for_scoring`, `for_generation`) build
    the Provider-Chain aus drei Konfigurations-Achsen, jeweils PRO ROLE:

      1. BEWERBER_<ROLE>_PROVIDER_ORDER   - z.B. "gemini,openai" oder "openai,gemini"
                                            Default: "openai,gemini"
      2. BEWERBER_<ROLE>_OPENAI_MODEL     - Model fuer alle OpenAI-Provider in
                                            der Kette (primary + fallback key).
                                            Resolution: ROLE-spez -> BEWERBER_LLM_MODEL
                                                       -> DEFAULT_MODEL
      3. BEWERBER_<ROLE>_GEMINI_MODEL     - Model fuer den Gemini-Provider.
                                            Resolution: ROLE-spez -> BEWERBER_GEMINI_MODEL
                                                       -> DEFAULT_GEMINI_MODEL

    Provider-Konstruktion ist resilient: Provider, deren Voraussetzungen
    fehlen (kein Key, kein installiertes Package), werden uebersprungen und
    geloggt, statt einen Crash zu provozieren.

    Damit ist der Anwendungsfall sauber abgebildet: Scoring kann primaer
    ueber Gemini laufen (gratis), Generation primaer ueber OpenAI (Qualitaet),
    jeweils mit dem jeweils ANDEREN Provider als Notnagel.
    """

    DEFAULT_MODEL = "gpt-5-mini"
    DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
    DEFAULT_PROVIDER_ORDER = "openai,gemini"
    RETRY_DELAY_S = 1.5
    # Circuit-Breaker: nach so vielen AUFEINANDERFOLGENDEN Fehlern wird ein
    # Provider fuer die Lebensdauer dieses Clients (= einen Run) uebersprungen.
    # Quota trippt schneller: erschoepfte Tages-Quota erholt sich nicht mid-run.
    QUOTA_TRIP_AFTER = 2
    TRANSIENT_TRIP_AFTER = 3

    def __init__(
        self,
        client: OpenAI | None = None,
        model: str | None = None,
        providers: list[_Provider] | None = None,
    ) -> None:
        # Breaker-Zustand je Provider-Index: consecutive-Fail-Zaehler + offen-Flag
        self._breaker: dict[int, dict[str, Any]] = {}
        if providers is not None:
            self.providers = list(providers)
            self.model = (
                providers[0].model if providers else (model or self.DEFAULT_MODEL)
            )
            return

        primary_model = model or os.environ.get("BEWERBER_LLM_MODEL", self.DEFAULT_MODEL)
        self.model = primary_model

        if client is not None:
            # Test-injection: single-provider chain wrapping the supplied OpenAI client
            self.providers = [OpenAIProvider(client=client, model=primary_model)]
            return

        self.providers = self._build_default_chain(primary_model)

    # ------------------------------------------------------------------
    # Role-specific factories: scoring (cheap, high-volume) vs. generation
    # (quality-sensitive, low-volume). Each provider in the chain bekommt
    # seinen EIGENEN Model-Namen - der Fragility-Bug, dass OpenAI mit einem
    # Gemini-Model-Namen aufgerufen wird, ist damit ausgeschlossen.
    # ------------------------------------------------------------------

    @classmethod
    def for_scoring(cls) -> "LLMClient":
        return cls(providers=cls._build_role_providers("SCORING"))

    @classmethod
    def for_generation(cls) -> "LLMClient":
        return cls(providers=cls._build_role_providers("GENERATION"))

    @classmethod
    def _build_role_providers(cls, role: str) -> list[_Provider]:
        """Build the chain for SCORING or GENERATION based on env config."""
        order_str = (
            os.environ.get(f"BEWERBER_{role}_PROVIDER_ORDER")
            or cls.DEFAULT_PROVIDER_ORDER
        )
        order = [p.strip().lower() for p in order_str.split(",") if p.strip()]

        openai_model = (
            os.environ.get(f"BEWERBER_{role}_OPENAI_MODEL")
            or os.environ.get("BEWERBER_LLM_MODEL")
            or cls.DEFAULT_MODEL
        )
        gemini_model = (
            os.environ.get(f"BEWERBER_{role}_GEMINI_MODEL")
            or os.environ.get("BEWERBER_GEMINI_MODEL")
            or cls.DEFAULT_GEMINI_MODEL
        )

        providers: list[_Provider] = []
        for name in order:
            if name == "openai":
                providers.extend(cls._build_openai_providers(openai_model))
            elif name == "gemini":
                providers.extend(cls._build_gemini_providers(gemini_model))
            else:
                log.warning(
                    "[LLM] Unbekannter Provider %r in BEWERBER_%s_PROVIDER_ORDER - uebersprungen",
                    name, role,
                )
        if not providers:
            log.warning(
                "[LLM] Kein einziger Provider fuer Rolle %s verfuegbar "
                "(weder OPENAI_API_KEY noch GOOGLE_API_KEY gesetzt?)",
                role,
            )
        return providers

    @staticmethod
    def _build_openai_providers(model: str) -> list[_Provider]:
        """OpenAI primary + optional fallback key, beide mit dem GLEICHEN Model."""
        out: list[_Provider] = []
        if os.environ.get("OPENAI_API_KEY"):
            out.append(OpenAIProvider(model=model))
        fb = os.environ.get("OPENAI_API_KEY_FALLBACK")
        if fb:
            out.append(OpenAIProvider(api_key=fb, model=model))
        return out

    @staticmethod
    def _build_gemini_providers(model: str) -> list[_Provider]:
        """Gemini-Provider nur, wenn GOOGLE_API_KEY gesetzt + Paket installiert."""
        if not os.environ.get("GOOGLE_API_KEY"):
            return []
        try:
            return [GeminiProvider(model=model)]
        except ImportError:
            log.warning("[LLM] google-genai nicht installiert - Gemini-Provider uebersprungen")
            return []

    @staticmethod
    def _build_default_chain(primary_model: str) -> list[_Provider]:
        """Legacy chain used by `LLMClient()` no-arg construction.

        Behaeltdas alte Verhalten: dasselbe Model fuer alle Provider. Wird nur
        von Tests / direkten Konstruktor-Aufrufen genutzt. Neue Code-Pfade
        sollten `for_scoring()` / `for_generation()` nehmen.
        """
        chain: list[_Provider] = [OpenAIProvider(model=primary_model)]
        if os.environ.get("OPENAI_API_KEY_FALLBACK"):
            chain.append(OpenAIProvider(
                api_key=os.environ["OPENAI_API_KEY_FALLBACK"],
                model=primary_model,
            ))
        if os.environ.get("GOOGLE_API_KEY"):
            gemini_model = os.environ.get(
                "BEWERBER_GEMINI_MODEL", LLMClient.DEFAULT_GEMINI_MODEL,
            )
            try:
                chain.append(GeminiProvider(model=gemini_model))
            except ImportError:
                log.warning("google-genai not installed; skipping Gemini fallback")
        return chain

    def structured(self, *, system: str, user: str, schema: Type[T]) -> T:
        return self._call_chain(
            lambda p: p.structured(system=system, user=user, schema=schema),
            label="structured",
        )

    def text(self, *, system: str, user: str) -> str:
        return self._call_chain(
            lambda p: p.text(system=system, user=user),
            label="text",
        )

    def _call_chain(self, fn: Callable[[_Provider], Any], *, label: str) -> Any:
        last_exc: Exception | None = None
        for idx, provider in enumerate(self.providers):
            br = self._breaker.setdefault(idx, {"quota": 0, "transient": 0, "open": False})
            if br["open"]:
                continue
            try:
                result = self._call_with_retry(fn, provider, label=label)
            except LLMQuotaExhausted as e:
                last_exc = e
                log.warning("[LLM/%s] %s quota exhausted; trying next provider", label, provider.name)
                br["quota"] += 1
                self._maybe_trip(br, provider, count=br["quota"], limit=self.QUOTA_TRIP_AFTER, reason="quota")
                continue
            except LLMTransientError as e:
                last_exc = e
                log.warning("[LLM/%s] %s transient error persists; trying next provider", label, provider.name)
                br["transient"] += 1
                self._maybe_trip(br, provider, count=br["transient"], limit=self.TRANSIENT_TRIP_AFTER, reason="transient")
                continue
            br["quota"] = 0
            br["transient"] = 0
            return result
        if last_exc is None:
            raise LLMAllProvidersFailed(
                f"All {len(self.providers)} provider(s) circuit-open "
                "(Quota/Netzfehler frueher in diesem Lauf)"
            )
        raise LLMAllProvidersFailed(
            f"All {len(self.providers)} provider(s) failed; last error: {last_exc}"
        ) from last_exc

    @staticmethod
    def _maybe_trip(br: dict[str, Any], provider: _Provider, *, count: int, limit: int, reason: str) -> None:
        if count >= limit and not br["open"]:
            br["open"] = True
            log.warning(
                "[LLM] %s circuit open nach %dx %s - wird fuer den Rest des Laufs uebersprungen",
                provider.name, count, reason,
            )

    def _call_with_retry(self, fn: Callable[[_Provider], Any], provider: _Provider, *, label: str) -> Any:
        try:
            return fn(provider)
        except LLMQuotaExhausted:
            raise
        except LLMTransientError as e:
            log.info(
                "[LLM/%s] %s transient error, retrying in %.1fs: %s",
                label, provider.name, self.RETRY_DELAY_S, e,
            )
            time.sleep(self.RETRY_DELAY_S)
            return fn(provider)
