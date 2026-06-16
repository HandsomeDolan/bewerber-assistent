"""Tests fuer den Setup-Wizard. Wir testen vor allem _build_env_text -
das ist die deterministische, einfach pruefbare Schicht.
Den interaktiven run_setup_wizard testen wir via click.testing.CliRunner
mit Eingabe-Stream.
"""
from pathlib import Path

import click.testing
import pytest

from bewerber.cli import main
from bewerber.setup_wizard import _build_env_text


def test_build_env_text_includes_all_keys():
    text = _build_env_text(
        openai_key="sk-test",
        openai_fallback="sk-fb",
        google_key="AIz-test",
        scoring_order="gemini,openai",
        generation_order="openai,gemini",
        scoring_openai_model="gpt-5-mini",
        generation_openai_model="gpt-5.1",
        scoring_gemini_model="gemini-2.5-flash",
        generation_gemini_model="gemini-2.5-flash",
        arbeitsagentur_key="ARB-key",
    )
    assert "OPENAI_API_KEY=sk-test" in text
    assert "OPENAI_API_KEY_FALLBACK=sk-fb" in text
    assert "GOOGLE_API_KEY=AIz-test" in text
    assert "BEWERBER_SCORING_PROVIDER_ORDER=gemini,openai" in text
    assert "BEWERBER_GENERATION_PROVIDER_ORDER=openai,gemini" in text
    assert "BEWERBER_SCORING_OPENAI_MODEL=gpt-5-mini" in text
    assert "BEWERBER_GENERATION_OPENAI_MODEL=gpt-5.1" in text
    assert "BEWERBER_SCORING_GEMINI_MODEL=gemini-2.5-flash" in text
    assert "ARBEITSAGENTUR_API_KEY=ARB-key" in text


def test_build_env_text_omits_provider_model_when_provider_unused():
    """Wenn der User 'nur Gemini' gewaehlt hat, kommen die OPENAI_MODEL-Zeilen NICHT in die Datei."""
    text = _build_env_text(
        openai_key="", openai_fallback="", google_key="AIz",
        scoring_order="gemini", generation_order="gemini",
        scoring_openai_model="", generation_openai_model="",
        scoring_gemini_model="gemini-2.5-flash",
        generation_gemini_model="gemini-2.5-flash",
        arbeitsagentur_key="",
    )
    assert "BEWERBER_SCORING_OPENAI_MODEL" not in text
    assert "BEWERBER_GENERATION_OPENAI_MODEL" not in text
    assert "BEWERBER_SCORING_GEMINI_MODEL=gemini-2.5-flash" in text


def test_setup_command_writes_env_via_cli_runner(tmp_path, monkeypatch):
    """End-to-end: bewerber setup mit gemockten Prompts -> .env auf Platte."""
    workspace = tmp_path / "ws"
    (workspace / "bewerber").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))

    runner = click.testing.CliRunner()
    # Provider=3 (beide), OpenAI-Key, kein Fallback, Gemini-Key,
    # Gemini-zuerst-fuer-Scoring=J, OpenAI-zuerst-fuer-Generation=J,
    # Arbeitsagentur-Key=N
    inputs = "\n".join([
        "3",          # Provider Wahl
        "sk-test",    # OpenAI Key
        "n",          # kein Fallback
        "AIz-test",   # Google Key
        "",           # Gemini zuerst fuer Scoring (default J -> Enter)
        "",           # OpenAI zuerst fuer Generation (default J -> Enter)
        "n",          # Arbeitsagentur nicht setzen
    ]) + "\n"
    result = runner.invoke(main, ["setup"], input=inputs)
    assert result.exit_code == 0, result.output

    env_path = workspace / "bewerber" / ".env"
    assert env_path.is_file()
    content = env_path.read_text()
    assert "OPENAI_API_KEY=sk-test" in content
    assert "GOOGLE_API_KEY=AIz-test" in content
    assert "BEWERBER_SCORING_PROVIDER_ORDER=gemini,openai" in content
    assert "BEWERBER_GENERATION_PROVIDER_ORDER=openai,gemini" in content
    assert "ARBEITSAGENTUR_API_KEY=\n" in content   # leer


def test_setup_refuses_overwrite_without_force(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    (workspace / "bewerber").mkdir(parents=True)
    (workspace / "bewerber" / ".env").write_text("ALREADY=here\n")
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))

    runner = click.testing.CliRunner()
    result = runner.invoke(main, ["setup"])
    assert result.exit_code != 0
    assert ".env existiert bereits" in result.output
    # File unveraendert
    assert (workspace / "bewerber" / ".env").read_text() == "ALREADY=here\n"


def test_setup_force_overwrites_existing_env(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    (workspace / "bewerber").mkdir(parents=True)
    (workspace / "bewerber" / ".env").write_text("OLD=value\n")
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))

    runner = click.testing.CliRunner()
    inputs = "\n".join([
        "1",          # nur Gemini
        "AIz-only",   # Google Key
        "n",          # Arbeitsagentur nicht
    ]) + "\n"
    result = runner.invoke(main, ["setup", "--force"], input=inputs)
    assert result.exit_code == 0, result.output

    content = (workspace / "bewerber" / ".env").read_text()
    assert "OLD=value" not in content
    assert "GOOGLE_API_KEY=AIz-only" in content
