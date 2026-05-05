from click.testing import CliRunner
from bewerber.cli import main


def test_cli_help_lists_command_groups():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "profile" in result.output
    assert "projects" in result.output


def test_profile_help_lists_subcommands():
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "sync" in result.output


def test_projects_help_lists_scan():
    runner = CliRunner()
    result = runner.invoke(main, ["projects", "--help"])
    assert result.exit_code == 0
    assert "scan" in result.output
