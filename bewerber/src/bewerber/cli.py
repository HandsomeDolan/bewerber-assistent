import tempfile
import webbrowser
from datetime import date
from datetime import datetime as _datetime
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

from bewerber.dashboard.render import render_dashboard
from bewerber.profile.extractor import (
    extract_profile_from_documents,
    save_anschreiben_examples,
)
from bewerber.profile.projects import scan_project
from bewerber.profile.sync import sync_projects_into_profile
from bewerber.setup_wizard import run_setup_wizard
from bewerber.shared.llm import LLMClient
from bewerber.shared.paths import Paths
from bewerber.tailoring.orchestrator import TailorInput, tailor, rebuild_pdfs
from bewerber.tailoring.posting import read_posting_from_file
from bewerber.tailoring.snapshot import snapshot_url
from bewerber.discovery.searches import load_searches
from bewerber.discovery.orchestrator import discover
# Import scraper modules so they self-register in scraper_registry
from bewerber.discovery.scrapers import arbeitsagentur as _arbeitsagentur  # noqa: F401
from bewerber.discovery.scrapers import linkedin as _linkedin  # noqa: F401
from bewerber.discovery.scrapers import indeed as _indeed  # noqa: F401
from bewerber.shared.state import load_state, save_state
from bewerber.shared.state_schema import JobStatus, StatusHistoryEntry

load_dotenv()


@click.group()
def main() -> None:
    """Bewerber-Assistent: Profil, Discovery, Tailoring, Dashboard."""


@main.group()
def profile() -> None:
    """Profil-Aufbau und -Pflege."""


@main.group()
def projects() -> None:
    """Projektordner-Management."""


@profile.command("init")
@click.option("--force", is_flag=True, help="Überschreibt existierende master_profile.yaml")
def profile_init(force: bool) -> None:
    """Erzeugt master_profile.yaml aus Bewerbungsunterlagen/."""
    paths = Paths()
    if paths.master_profile.exists() and not force:
        click.echo(
            f"master_profile.yaml existiert bereits in {paths.bewerber_dir}. "
            "Mit --force überschreiben."
        )
        raise click.exceptions.Exit(1)

    if not paths.bewerbungsunterlagen.is_dir():
        click.echo(f"Bewerbungsunterlagen nicht gefunden: {paths.bewerbungsunterlagen}")
        raise click.exceptions.Exit(1)

    llm = LLMClient.for_scoring()  # one-shot Extraktion, kein Vollmodell noetig
    click.echo(f"Lese Dokumente aus {paths.bewerbungsunterlagen} … [{llm.model}]")
    profile = extract_profile_from_documents(paths.bewerbungsunterlagen, llm=llm)
    click.echo(f"Extrahiert: {profile.person.name}, {len(profile.berufserfahrung)} Stellen")

    bewerbungen = paths.bewerbungen
    selected: list = []
    if bewerbungen.is_dir():
        candidates = sorted(
            f for f in bewerbungen.iterdir()
            if f.is_file() and f.suffix.lower() in {".pdf", ".docx"}
        )
        if candidates:
            click.echo("\nVerfügbare bisherige Bewerbungen für Stil-Few-Shots:")
            for i, f in enumerate(candidates, start=1):
                click.echo(f"  [{i:>2}] {f.name}")
            answer = click.prompt(
                "Welche als Stil-Beispiele speichern? (Nummern komma-separiert, leer = keine)",
                default="",
                show_default=False,
            )
            if answer.strip():
                indices = [int(x) for x in answer.split(",") if x.strip().isdigit()]
                selected = [candidates[i - 1] for i in indices if 1 <= i <= len(candidates)]

    if selected:
        saved = save_anschreiben_examples(selected, paths.anschreiben_examples)
        click.echo(f"{len(saved)} Anschreiben-Beispiele gespeichert in {paths.anschreiben_examples}")

    paths.bewerber_dir.mkdir(parents=True, exist_ok=True)
    data = profile.model_dump(exclude_none=True)
    data["projekte"] = []  # populated by `profile sync` later
    with paths.master_profile.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    click.echo(f"\n✔ master_profile.yaml geschrieben: {paths.master_profile}")
    click.echo("Nächster Schritt: `bewerber projects scan` und `bewerber profile sync`.")


@profile.command("sync")
def profile_sync() -> None:
    """Merged _profile.md aus Projektordnern in master_profile.yaml."""
    n = sync_projects_into_profile()
    paths = Paths()
    click.echo(f"{n} Projekte synchronisiert → {paths.master_profile}")


@projects.command("scan")
@click.option("--force", is_flag=True, help="Überschreibe bestehende _profile.md")
def projects_scan(force: bool) -> None:
    """Erzeugt _profile.md in jedem Projektordner."""
    paths = Paths()
    llm = LLMClient.for_scoring()
    folders = paths.project_folders()
    if not folders:
        click.echo(f"Keine Projektordner gefunden in {paths.documents}")
        return
    click.echo(f"Scanne {len(folders)} Projektordner …")
    for folder in folders:
        result = scan_project(folder, llm=llm, force=force)
        if result is None:
            click.echo(f"  skip (existiert): {folder.name}")
        else:
            click.echo(f"  ok:  {folder.name} → {result.name}")
    click.echo("Fertig.")


@main.command("tailor")
@click.option("--url", help="URL der Stellenausschreibung (wird via Playwright gesnapshotet).")
@click.option("--posting-file", "posting_file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Pfad zu einer Ausschreibung als .txt/.pdf/.docx.")
@click.option("--firma", help="Firmenname (für Ordnername + Anschreiben).")
@click.option("--rolle", help="Rollenbezeichnung (für Ordnername + Betreff).")
@click.option("--kontakt", "kontakt_name", help="Name der Ansprechperson (für Anrede).")
@click.option("--datum", help="Datum YYYY-MM-DD (default: heute).")
@click.option("--starttermin", help="Frühester Eintrittstermin (z. B. 'ab sofort', '2026-08-01'). Wird im Anschreiben-Schluss erwähnt.")
@click.option("--gehalt", help="Gehaltsvorstellung brutto/Jahr (optional, z. B. '65.000 EUR'). Wird im Anschreiben-Schluss erwähnt.")
@click.option("--rebuild", "rebuild_dir", type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Nur PDFs neu aus dem Bewerbungsordner rendern (keine LLM-Aufrufe).")
def cmd_tailor(url, posting_file, firma, rolle, kontakt_name, datum, starttermin, gehalt, rebuild_dir):
    """Erzeugt tailored Lebenslauf + Anschreiben für eine Stellenausschreibung."""
    if rebuild_dir:
        click.echo(f"Re-rendere PDFs aus {rebuild_dir} …")
        rebuild_pdfs(rebuild_dir)
        click.echo("Fertig.")
        return

    if not url and not posting_file:
        click.echo("Fehler: --url ODER --posting-file muss angegeben werden (oder --rebuild).")
        raise click.exceptions.Exit(1)
    if url and posting_file:
        click.echo("Fehler: --url und --posting-file nicht gleichzeitig.")
        raise click.exceptions.Exit(1)
    if not firma or not rolle:
        click.echo("Fehler: --firma und --rolle sind erforderlich.")
        raise click.exceptions.Exit(1)

    datum = datum or date.today().isoformat()
    llm = LLMClient.for_generation()  # Anschreiben + Customize: Qualitaet vor Kosten
    click.echo(f"  LLM-Modell: {llm.model}")
    snapshot_dir: Path | None = None

    if posting_file:
        posting = read_posting_from_file(posting_file)
        posting_text = posting.description
        source_url = None
        click.echo(f"Lese Ausschreibung aus {posting_file.name} …")
    else:
        click.echo(f"Snapshot {url} …")
        snapshot_dir = Path(tempfile.mkdtemp(prefix="bewerber-snap-"))
        posting_text = snapshot_url(url, snapshot_dir)
        source_url = url

    click.echo("Generiere Lebenslauf + Anschreiben …")
    result = tailor(TailorInput(
        posting_text=posting_text,
        firma=firma, rolle=rolle, datum=datum,
        kontakt_name=kontakt_name,
        source_url=source_url,
        snapshot_dir=snapshot_dir,
        llm=llm,
        starttermin=starttermin,
        gehalt=gehalt,
    ))
    click.echo(f"\n✔ Bewerbungsordner: {result.output_dir}")
    click.echo(f"  • Lebenslauf:    {result.lebenslauf_pdf.name}")
    click.echo(f"  • Anschreiben:   {result.anschreiben_pdf.name}")


@main.command("discover")
def cmd_discover() -> None:
    """Sucht Jobs auf den konfigurierten Boards, scort sie gegen master_profile, schreibt state.json."""
    paths = Paths()
    if not paths.master_profile.is_file():
        click.echo(f"Fehler: {paths.master_profile} fehlt. Erst `bewerber profile init` ausführen.")
        raise click.exceptions.Exit(1)
    searches_path = paths.bewerber_dir / "searches.yaml"
    if not searches_path.is_file():
        click.echo(
            f"Fehler: {searches_path} fehlt. "
            f"Kopiere `bewerber/searches.yaml.example` zu `bewerber/searches.yaml` und passe sie an."
        )
        raise click.exceptions.Exit(1)

    config = load_searches(searches_path)
    if not config.searches:
        click.echo("Keine Sucheinträge in searches.yaml definiert. Nichts zu tun.")
        return

    click.echo(f"Lade {len(config.searches)} Sucheinträge …")
    master_yaml_text = paths.master_profile.read_text(encoding="utf-8")
    state = load_state(paths.state_json)
    llm = LLMClient.for_scoring()  # Klassifikation pro Job - gpt-5-mini reicht
    click.echo(f"  Scoring-Modell: {llm.model}")
    discover(config, state=state, master_yaml_text=master_yaml_text, llm=llm)
    save_state(paths.state_json, state)

    fit_jobs = [j for j in state.jobs.values() if j.scoring and j.scoring.fit_score >= config.defaults.min_fit_score]
    click.echo(f"✔ {len(state.jobs)} Jobs insgesamt, {len(fit_jobs)} davon mit Fit-Score >= {config.defaults.min_fit_score}")
    if state.scrape_errors:
        click.echo("Scrape-Fehler:")
        for board, err in state.scrape_errors.items():
            click.echo(f"  · {board}: {err.last_error}")


def _parse_status(value: str) -> JobStatus:
    try:
        return JobStatus(value)
    except ValueError:
        valid = ", ".join(s.value for s in JobStatus)
        raise click.BadParameter(f"Ungültiger Status {value!r}. Erlaubt: {valid}")


@main.command("mark")
@click.argument("job_id")
@click.argument("status", callback=lambda ctx, param, val: _parse_status(val))
@click.option("--link", "application_link", help="URL der eingereichten Bewerbung (für Status `applied`).")
@click.option("--at", "interview_at", help="Datum/Zeit eines Interviews (ISO oder freie Form).")
def cmd_mark(job_id: str, status: JobStatus, application_link: str | None, interview_at: str | None) -> None:
    """Setzt den Status einer Bewerbung (discovered/shortlisted/tailored/applied/interview/offer/rejected/withdrawn)."""
    paths = Paths()
    state = load_state(paths.state_json)
    if job_id not in state.jobs:
        click.echo(f"Job-ID {job_id!r} nicht gefunden in {paths.state_json}.")
        raise click.exceptions.Exit(1)
    job = state.jobs[job_id]
    job.status = status
    job.status_history.append(StatusHistoryEntry(
        status=status,
        at=_datetime.now().isoformat(timespec="seconds"),
    ))
    if application_link:
        job.application_link = application_link
    if interview_at:
        job.interview_scheduled = interview_at
    save_state(paths.state_json, state)
    click.echo(f"✔ {job_id} → {status.value}")


@main.command("note")
@click.argument("job_id")
@click.argument("text")
def cmd_note(job_id: str, text: str) -> None:
    """Fügt eine Notiz zur Bewerbung hinzu (chronologisch, je Aufruf eine neue Zeile)."""
    paths = Paths()
    state = load_state(paths.state_json)
    if job_id not in state.jobs:
        click.echo(f"Job-ID {job_id!r} nicht gefunden.")
        raise click.exceptions.Exit(1)
    job = state.jobs[job_id]
    stamp = _datetime.now().strftime("%Y-%m-%d %H:%M")
    new_entry = f"[{stamp}] {text}"
    job.notes = f"{job.notes}\n{new_entry}".strip() if job.notes else new_entry
    save_state(paths.state_json, state)
    click.echo(f"✔ Notiz hinzugefügt zu {job_id}")


@main.command("regen")
def cmd_regen() -> None:
    """Rendert dashboard.html aus aktuellem state.json neu."""
    paths = Paths()
    state = load_state(paths.state_json)
    html = render_dashboard(state)
    paths.dashboard_html.write_text(html, encoding="utf-8")
    click.echo(f"✔ Dashboard geschrieben: {paths.dashboard_html} ({len(state.jobs)} Jobs)")


@main.command("setup")
@click.option("--force", is_flag=True, help="Bestehende .env ueberschreiben.")
def cmd_setup(force: bool) -> None:
    """Interaktiver Einrichtungs-Wizard fuer die .env-Datei.

    Fragt API-Keys + Provider-Reihenfolge ab und schreibt eine .env in
    den bewerber/-Ordner. Standardmaessig wird eine vorhandene .env NICHT
    ueberschrieben (Schutz vor versehentlichem Verlust der API-Keys).
    """
    run_setup_wizard(force=force)


@main.command("serve")
@click.option("--port", type=int, default=0, help="HTTP-Port (default: ephemeral).")
@click.option("--no-browser", is_flag=True, help="Browser nicht automatisch öffnen.")
def cmd_serve(port: int, no_browser: bool) -> None:
    """Startet lokalen HTTP-Server für interaktives Dashboard.

    Im Gegensatz zum file:// Mode kann das Dashboard hier echte Statusänderungen
    schreiben (Beworben-Checkbox, Notizen, Ordner öffnen).
    Beenden mit Ctrl+C.
    """
    from bewerber.dashboard.server import serve as start_server
    paths = Paths()
    # Erstmaliger Start: .env fehlt -> Setup-Wizard anstossen
    env_path = paths.bewerber_dir / ".env"
    if not env_path.is_file():
        click.echo("Keine .env gefunden - starte Setup-Wizard ...\n")
        run_setup_wizard()
        load_dotenv(env_path, override=True)  # Env-Werte ins laufende Prozess-os.environ ziehen
    # Also write a static dashboard.html so the file is up-to-date for offline use.
    state = load_state(paths.state_json)
    paths.dashboard_html.write_text(render_dashboard(state), encoding="utf-8")

    server = start_server(paths=paths, port=port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    click.echo(f"✔ Dashboard läuft auf {url}")
    click.echo(f"  Statisches Backup: {paths.dashboard_html}")
    click.echo("  Ctrl+C zum Beenden.")
    if not no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nServer gestoppt.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
