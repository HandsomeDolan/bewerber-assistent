import click
import yaml
from dotenv import load_dotenv

from bewerber.profile.extractor import (
    extract_profile_from_documents,
    save_anschreiben_examples,
)
from bewerber.profile.projects import scan_project
from bewerber.profile.sync import sync_projects_into_profile
from bewerber.shared.llm import LLMClient
from bewerber.shared.paths import Paths

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

    llm = LLMClient()
    click.echo(f"Lese Dokumente aus {paths.bewerbungsunterlagen} …")
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
    llm = LLMClient()
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


if __name__ == "__main__":
    main()
