import os
from typing import Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Thin wrapper around OpenAI Responses API with structured outputs."""

    DEFAULT_MODEL = "gpt-5.1-mini"

    def __init__(self, client: OpenAI | None = None, model: str | None = None) -> None:
        self.client = client or OpenAI()
        self.model = model or os.environ.get("BEWERBER_LLM_MODEL", self.DEFAULT_MODEL)

    def structured(self, *, system: str, user: str, schema: Type[T]) -> T:
        """Call LLM with a pydantic schema as required output format."""
        resp = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=schema,
        )
        return resp.output_parsed

    def text(self, *, system: str, user: str) -> str:
        """Call LLM for free-form text output (e.g. cover letters)."""
        resp = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.output_text
