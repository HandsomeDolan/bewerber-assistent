import yaml
from pathlib import Path
from click.testing import CliRunner
from bewerber.cli import main


def _write_master_and_searches(workspace: Path, documents: Path) -> None:
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True, exist_ok=True)
    (bewerber_dir / "master_profile.yaml").write_text(yaml.safe_dump({
        "person": {"name": "Steve", "email": "s@x.de"},
        "berufsprofil": "kurz",
        "zielposition": [],
    }, allow_unicode=True))
    (bewerber_dir / "searches.yaml").write_text(yaml.safe_dump({
        "defaults": {"locations": ["Leipzig"], "date_posted_max_days": 14, "min_fit_score": 6},
        "searches": [{"name": "KI", "keywords": ["KI Manager"], "boards": ["arbeitsagentur"]}],
    }, allow_unicode=True))
    (documents / "Bewerbungsunterlagen" / "Bewerbungen").mkdir(parents=True)


def test_discover_loads_config_and_calls_orchestrator(tmp_path, monkeypatch, mocker):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    _write_master_and_searches(workspace, tmp_path)

    fake_discover = mocker.patch("bewerber.cli.discover")
    mocker.patch("bewerber.cli.LLMClient")

    runner = CliRunner()
    result = runner.invoke(main, ["discover"])
    assert result.exit_code == 0, result.output
    fake_discover.assert_called_once()
    # Output mentions the count of searches
    assert "1 Suche" in result.output or "1 search" in result.output.lower() or "Sucheinträge" in result.output


def test_discover_fails_if_searches_yaml_missing(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    (workspace / "bewerber").mkdir(parents=True)
    (workspace / "bewerber" / "master_profile.yaml").write_text("person: {name: x, email: x@y.de}\nberufsprofil: x\nzielposition: []")
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))

    runner = CliRunner()
    result = runner.invoke(main, ["discover"])
    assert result.exit_code != 0
    assert "searches.yaml" in result.output


def test_discover_fails_if_master_profile_missing(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    (workspace / "bewerber").mkdir(parents=True)
    (workspace / "bewerber" / "searches.yaml").write_text("defaults: {}\nsearches: []")
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))

    runner = CliRunner()
    result = runner.invoke(main, ["discover"])
    assert result.exit_code != 0
    assert "master_profile.yaml" in result.output
