"""Interaktiver Setup-Wizard fuer die .env-Datei.

Wird beim ersten Start automatisch ausgeloest, wenn die .env fehlt - kann
aber auch manuell ueber `bewerber setup` aufgerufen werden, um Keys
nachzutragen oder zu aktualisieren.

Konfiguriert wird ausschliesslich .env. Master-Profil, Suchen, Anlagen
laufen ueber den Web-Onboarding-Wizard (siehe /onboarding).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from bewerber.shared.paths import Paths


def _prompt(msg: str, *, default: str = "", secret: bool = False, allow_empty: bool = False) -> str:
    while True:
        val = click.prompt(
            msg, default=default, show_default=bool(default),
            hide_input=secret, type=str,
        ).strip()
        if val or allow_empty:
            return val
        click.echo("  ⚠ Eingabe darf nicht leer sein.")


def run_setup_wizard(*, force: bool = False) -> Path:
    """Schreibt eine neue .env per interaktivem Prompt.

    Args:
        force: wenn True, ueberschreibt eine vorhandene .env nach Rueckfrage.
               wenn False und .env existiert, wird abgebrochen.

    Returns:
        Pfad der geschriebenen .env.
    """
    paths = Paths()
    env_path = paths.bewerber_dir / ".env"

    if env_path.is_file() and not force:
        click.echo(f"✗ .env existiert bereits: {env_path}")
        click.echo("  Mit `bewerber setup --force` ueberschreiben oder manuell editieren.")
        raise click.exceptions.Exit(1)

    click.echo()
    click.secho("=" * 60, fg="cyan")
    click.secho("  Bewerber-Assistent - Erstmaliges Setup", fg="cyan", bold=True)
    click.secho("=" * 60, fg="cyan")
    click.echo(
        "Wir richten jetzt die .env-Datei mit deinen API-Keys ein.\n"
        "Du brauchst MINDESTENS einen LLM-Provider (OpenAI ODER Gemini).\n"
        "Alle Felder koennen spaeter manuell in der .env angepasst werden.\n"
    )

    # --- LLM-Provider waehlen ---
    click.secho("Schritt 1/3: LLM-Provider", fg="yellow", bold=True)
    click.echo(
        "  [1] Nur Gemini  (kostenloser Free-Tier bis ~1500 Requests/Tag)\n"
        "  [2] Nur OpenAI  (gpt-5/5.1 Reihe, kostenpflichtig)\n"
        "  [3] Beide  (Gemini primaer fuer Scoring + OpenAI fuer Anschreiben)  -- empfohlen"
    )
    while True:
        choice = click.prompt("Auswahl", default="3", type=str).strip()
        if choice in ("1", "2", "3"):
            break
        click.echo("  ⚠ Bitte 1, 2 oder 3 eingeben.")

    use_openai = choice in ("2", "3")
    use_gemini = choice in ("1", "3")

    openai_key = ""
    openai_fallback = ""
    google_key = ""

    if use_openai:
        click.echo()
        click.secho("  OpenAI:", fg="cyan")
        openai_key = _prompt(
            "  API Key (sk-... von https://platform.openai.com/api-keys)",
            secret=True,
        )
        if click.confirm("  Optional: zweiten OpenAI-Key als Fallback hinzufuegen?", default=False):
            openai_fallback = _prompt("  Fallback API Key", secret=True)

    if use_gemini:
        click.echo()
        click.secho("  Gemini (Google AI Studio):", fg="cyan")
        google_key = _prompt(
            "  API Key (AIza... von https://aistudio.google.com/apikey)",
            secret=True,
        )

    # --- Provider-Order ---
    click.echo()
    click.secho("Schritt 2/3: Provider-Reihenfolge", fg="yellow", bold=True)
    if use_openai and use_gemini:
        click.echo(
            "  Scoring (haeufiger LLM-Call, kostenrelevant):  Gemini zuerst, OpenAI als Fallback?  [J/n]"
        )
        gemini_first_scoring = click.confirm("  -> ", default=True)
        click.echo(
            "  Generation (Anschreiben, Qualitaets-kritisch):  OpenAI zuerst, Gemini als Fallback?  [J/n]"
        )
        openai_first_generation = click.confirm("  -> ", default=True)
        scoring_order = "gemini,openai" if gemini_first_scoring else "openai,gemini"
        generation_order = "openai,gemini" if openai_first_generation else "gemini,openai"
    elif use_openai:
        scoring_order = "openai"
        generation_order = "openai"
    else:
        scoring_order = "gemini"
        generation_order = "gemini"

    # --- Modelle ---
    scoring_openai_model = "gpt-5-mini" if use_openai else ""
    generation_openai_model = "gpt-5.1" if use_openai else ""
    scoring_gemini_model = "gemini-2.5-flash" if use_gemini else ""
    generation_gemini_model = "gemini-2.5-flash" if use_gemini else ""

    # --- Arbeitsagentur (optional) ---
    click.echo()
    click.secho("Schritt 3/3: Arbeitsagentur (optional)", fg="yellow", bold=True)
    click.echo(
        "  Fuer das automatische Scrapen der Arbeitsagentur brauchst du einen API-Key.\n"
        "  Beantragung: https://jobsuche.api.bund.dev/  - kann auch spaeter nachgetragen werden."
    )
    arbeitsagentur_key = ""
    if click.confirm("  API Key jetzt eintragen?", default=False):
        arbeitsagentur_key = _prompt("  Arbeitsagentur API Key", secret=True)

    # --- .env schreiben ---
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_text = _build_env_text(
        openai_key=openai_key,
        openai_fallback=openai_fallback,
        google_key=google_key,
        scoring_order=scoring_order,
        generation_order=generation_order,
        scoring_openai_model=scoring_openai_model,
        generation_openai_model=generation_openai_model,
        scoring_gemini_model=scoring_gemini_model,
        generation_gemini_model=generation_gemini_model,
        arbeitsagentur_key=arbeitsagentur_key,
    )
    env_path.write_text(env_text, encoding="utf-8")
    # Sicherheit: .env nur fuer den User lesbar
    try:
        env_path.chmod(0o600)
    except OSError:
        pass

    click.echo()
    click.secho(f"✓ .env geschrieben: {env_path}", fg="green", bold=True)
    click.echo()
    click.echo("Naechste Schritte:")
    click.echo("  1. Server starten:        `bewerber serve`")
    click.echo("  2. Im Browser einloggen + Profil-Onboarding via Web-Wizard")
    click.echo()
    return env_path


def _build_env_text(
    *,
    openai_key: str,
    openai_fallback: str,
    google_key: str,
    scoring_order: str,
    generation_order: str,
    scoring_openai_model: str,
    generation_openai_model: str,
    scoring_gemini_model: str,
    generation_gemini_model: str,
    arbeitsagentur_key: str,
) -> str:
    lines: list[str] = ["# Generiert vom Setup-Wizard. Manuelle Aenderungen sind ok.", ""]
    lines.append("# --- API Keys ---")
    lines.append(f"OPENAI_API_KEY={openai_key}")
    lines.append(f"OPENAI_API_KEY_FALLBACK={openai_fallback}")
    lines.append(f"GOOGLE_API_KEY={google_key}")
    lines.append("")
    lines.append("# --- LLM-Provider-Konfiguration ---")
    lines.append(f"BEWERBER_SCORING_PROVIDER_ORDER={scoring_order}")
    lines.append(f"BEWERBER_GENERATION_PROVIDER_ORDER={generation_order}")
    if scoring_openai_model:
        lines.append(f"BEWERBER_SCORING_OPENAI_MODEL={scoring_openai_model}")
    if generation_openai_model:
        lines.append(f"BEWERBER_GENERATION_OPENAI_MODEL={generation_openai_model}")
    if scoring_gemini_model:
        lines.append(f"BEWERBER_SCORING_GEMINI_MODEL={scoring_gemini_model}")
    if generation_gemini_model:
        lines.append(f"BEWERBER_GENERATION_GEMINI_MODEL={generation_gemini_model}")
    lines.append("")
    lines.append("# --- Datenquellen ---")
    lines.append(f"ARBEITSAGENTUR_API_KEY={arbeitsagentur_key}")
    lines.append("")
    return "\n".join(lines)
