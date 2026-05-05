import click
from dotenv import load_dotenv

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
    click.echo("not yet implemented")
    raise click.exceptions.Exit(2)


@projects.command("scan")
@click.option("--force", is_flag=True, help="Überschreibe bestehende _profile.md")
def projects_scan(force: bool) -> None:
    """Erzeugt _profile.md in jedem Projektordner."""
    click.echo(f"not yet implemented (force={force})")
    raise click.exceptions.Exit(2)


if __name__ == "__main__":
    main()
