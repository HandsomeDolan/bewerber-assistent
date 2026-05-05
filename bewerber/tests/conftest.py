import os
import pytest
from pathlib import Path


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def disable_real_openai(monkeypatch):
    """Prevent accidental real LLM calls in unit tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
