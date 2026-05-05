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


def test_projects_scan_iterates_folders(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 First").mkdir()
    (tmp_path / "1 First" / "README.md").write_text("# First")
    (tmp_path / "2 Second").mkdir()
    (tmp_path / "2 Second" / "README.md").write_text("# Second")
    (tmp_path / "ignored.txt").touch()

    fake_scan = mocker.patch("bewerber.cli.scan_project")
    fake_scan.return_value = tmp_path / "1 First" / "_profile.md"
    mocker.patch("bewerber.cli.LLMClient")

    runner = CliRunner()
    result = runner.invoke(main, ["projects", "scan"])
    assert result.exit_code == 0, result.output
    assert fake_scan.call_count == 2


def test_projects_scan_passes_force_flag(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 X").mkdir()
    fake_scan = mocker.patch("bewerber.cli.scan_project")
    mocker.patch("bewerber.cli.LLMClient")

    runner = CliRunner()
    result = runner.invoke(main, ["projects", "scan", "--force"])
    assert result.exit_code == 0
    _, kwargs = fake_scan.call_args
    assert kwargs.get("force") is True
