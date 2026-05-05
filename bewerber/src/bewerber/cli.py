import click
from dotenv import load_dotenv

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
def profile_init() -> None:
    """Erzeugt master_profile.yaml aus Bewerbungsunterlagen/."""
    click.echo("not yet implemented")
    raise click.exceptions.Exit(2)


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
