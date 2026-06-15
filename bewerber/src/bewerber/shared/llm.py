"""LLM client with multi-provider fallback chain.

Default chain (in order):
  1. OpenAI primary  - OPENAI_API_KEY,          model = BEWERBER_LLM_MODEL or 'gpt-5.1-mini'
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
            self.client = OpenAI(api_key=api_key)
        else:
            self.client = OpenAI()
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

    Structured outputs use Gemini's native `response_schema` when the pydantic
    schema is supported; for complex schemas, the SDK silently falls back to
    JSON-mode and we re-validate via `schema.model_validate_json(resp.text)`.
    """

    def __init__(self, *, api_key: str | None = None, model: str, client: Any = None) -> None:
        # Lazy import: only load google-genai when this provider is actually constructed
        from google import genai  # noqa: WPS433
        self.model = model
        self.client = client or genai.Client(api_key=api_key or os.environ.get("GOOGLE_API_KEY"))
        self.name = f"gemini:{model}"

    def structured(self, *, system: str, user: str, schema: Type[T]) -> T:
        from google.genai import errors as gerrors  # noqa: WPS433
        from google.genai import types as gtypes  # noqa: WPS433
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=gtypes.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        except gerrors.ClientError as e:
            self._raise_classified(e)
        except gerrors.ServerError as e:
            raise LLMTransientError(f"{self.name}: {e}") from e
        # Prefer SDK-parsed object; fall back to JSON-string parse
        if getattr(resp, "parsed", None) is not None:
            return resp.parsed  # type: ignore[return-value]
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
        return resp.text or ""

    def _raise_classified(self, e: Any) -> None:
        # google.genai.errors.ClientError has .code (HTTP) and .status (string)
        status = getattr(e, "status", "") or ""
        if status == "RESOURCE_EXHAUSTED":
            raise LLMQuotaExhausted(f"{self.name}: {e}") from e
        # Other 4xx (auth, bad request) shouldn't fall back blindly to next provider
        raise


class LLMClient:
    """Multi-provider LLM client with quota-fallback + transient retry."""

    DEFAULT_MODEL = "gpt-5.1-mini"
    DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-exp"
    RETRY_DELAY_S = 1.5

    def __init__(
        self,
        client: OpenAI | None = None,
        model: str | None = None,
        providers: list[_Provider] | None = None,
    ) -> None:
        if providers is not None:
            self.providers = list(providers)
            self.model = providers[0].model if providers else (model or self.DEFAULT_MODEL)
            return

        primary_model = model or os.environ.get("BEWERBER_LLM_MODEL", self.DEFAULT_MODEL)
        self.model = primary_model

        if client is not None:
            # Test-injection: single-provider chain wrapping the supplied OpenAI client
            self.providers = [OpenAIProvider(client=client, model=primary_model)]
            return

        self.providers = self._build_default_chain(primary_model)

    @staticmethod
    def _build_default_chain(primary_model: str) -> list[_Provider]:
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
        for provider in self.providers:
            try:
                return self._call_with_retry(fn, provider, label=label)
            except LLMQuotaExhausted as e:
                last_exc = e
                log.warning("[LLM/%s] %s quota exhausted; trying next provider", label, provider.name)
            except LLMTransientError as e:
                last_exc = e
                log.warning("[LLM/%s] %s transient error persists; trying next provider", label, provider.name)
        raise LLMAllProvidersFailed(
            f"All {len(self.providers)} provider(s) failed; last error: {last_exc}"
        ) from last_exc

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
