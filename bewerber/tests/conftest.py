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


@pytest.fixture(autouse=True)
def _isolate_workspace(tmp_path_factory, monkeypatch):
    """Schutz: kein Test darf je auf den ECHTEN Workspace schreiben.

    Setzt BEWERBER_WORKSPACE per Default auf ein frisches tmp-Verzeichnis.
    Tests, die einen eigenen Workspace brauchen, ueberschreiben das via
    monkeypatch.setenv in ihrer eigenen Fixture/Body (laeuft nach autouse,
    gewinnt also). Ohne diesen Guard wuerde Paths() auf das echte
    bewerber/-Verzeichnis zeigen und z.B. master_profile.yaml ueberschreiben.
    """
    ws = tmp_path_factory.mktemp("ws_guard")
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(ws))
    (ws / "bewerber").mkdir(exist_ok=True)
