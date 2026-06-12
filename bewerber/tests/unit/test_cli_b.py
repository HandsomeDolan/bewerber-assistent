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


from bewerber.shared.state import save_state, load_state
from bewerber.shared.state_schema import BewerberState, RawJob, TrackedJob, JobStatus


def _seed_state(workspace: Path) -> Path:
    bd = workspace / "bewerber"
    bd.mkdir(parents=True, exist_ok=True)
    job = TrackedJob(raw=RawJob(
        board="arbeitsagentur", external_id="x1",
        url="https://x", title="t", company="c", location="l",
    ))
    state = BewerberState(jobs={"arbeitsagentur-x1": job})
    state_path = bd / "state.json"
    save_state(state_path, state)
    return state_path


def test_mark_updates_status_and_appends_history(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    state_path = _seed_state(workspace)

    runner = CliRunner()
    result = runner.invoke(main, ["mark", "arbeitsagentur-x1", "applied", "--link", "https://applied.example"])
    assert result.exit_code == 0, result.output

    state = load_state(state_path)
    job = state.jobs["arbeitsagentur-x1"]
    assert job.status == JobStatus.APPLIED
    assert job.application_link == "https://applied.example"
    assert len(job.status_history) == 1
    assert job.status_history[0].status == JobStatus.APPLIED


def test_mark_invalid_status_rejected(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    _seed_state(workspace)
    runner = CliRunner()
    result = runner.invoke(main, ["mark", "arbeitsagentur-x1", "applied-yesterday"])
    assert result.exit_code != 0


def test_mark_unknown_job_id(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    _seed_state(workspace)
    runner = CliRunner()
    result = runner.invoke(main, ["mark", "nonexistent-9999", "applied"])
    assert result.exit_code != 0
    assert "nicht gefunden" in result.output.lower() or "unknown" in result.output.lower()


def test_note_appends_to_notes_field(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    state_path = _seed_state(workspace)

    runner = CliRunner()
    r1 = runner.invoke(main, ["note", "arbeitsagentur-x1", "Telefoniert am 13.06."])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(main, ["note", "arbeitsagentur-x1", "Interview-Einladung erhalten."])
    assert r2.exit_code == 0

    state = load_state(state_path)
    notes = state.jobs["arbeitsagentur-x1"].notes
    assert "Telefoniert" in notes
    assert "Interview-Einladung" in notes


def test_regen_writes_dashboard_html(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    _seed_state(workspace)

    runner = CliRunner()
    result = runner.invoke(main, ["regen"])
    assert result.exit_code == 0, result.output

    html = (workspace / "bewerber" / "dashboard.html").read_text(encoding="utf-8")
    assert "Bewerber-Dashboard" in html
    assert "arbeitsagentur-x1" in html


def test_serve_calls_regen_then_open(tmp_path, monkeypatch, mocker):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    _seed_state(workspace)

    fake_open = mocker.patch("bewerber.cli.webbrowser.open")
    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 0, result.output
    assert (workspace / "bewerber" / "dashboard.html").is_file()
    fake_open.assert_called_once()
    url = fake_open.call_args.args[0]
    assert url.startswith("file://")
    assert "dashboard.html" in url
