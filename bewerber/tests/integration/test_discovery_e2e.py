import yaml
from datetime import date
from pathlib import Path
from click.testing import CliRunner

from bewerber.cli import main
from bewerber.shared.state import load_state
from bewerber.shared.state_schema import JobStatus, RawJob, Scoring


def _setup_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "Bewerber_Assistent"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    (tmp_path / "Bewerbungsunterlagen" / "Bewerbungen").mkdir(parents=True)
    (bewerber_dir / "master_profile.yaml").write_text(yaml.safe_dump({
        "person": {"name": "Steve", "email": "s@x.de"},
        "berufsprofil": "kurz",
        "zielposition": ["KI Manager"],
    }, allow_unicode=True))
    (bewerber_dir / "searches.yaml").write_text(yaml.safe_dump({
        "defaults": {"locations": ["Leipzig"], "date_posted_max_days": 14, "min_fit_score": 6},
        "searches": [{"name": "KI", "keywords": ["KI Manager"], "boards": ["arbeitsagentur"]}],
    }, allow_unicode=True))
    return workspace


def test_full_discover_mark_regen_workflow(tmp_path, monkeypatch, mocker):
    workspace = _setup_workspace(tmp_path)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    # Mock scraper to return one job; mock enrich+score
    fake_adapter = mocker.Mock()
    fake_adapter.name = "arbeitsagentur"
    fake_adapter.search.return_value = [RawJob(
        board="arbeitsagentur", external_id="10001-1003091744-S",
        url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003091744-S",
        title="Business AI Consultant",
        company="2b AHEAD ThinkTank GmbH",
        location="Leipzig",
        posted_date=date(2026, 5, 19),
        description="Wir suchen einen erfahrenen Berater.",
        description_hash="abc123",
    )]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": fake_adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=9, begruendung="Sehr starkes Match.",
        matched_skills=["n8n", "Python"],
        missing_skills=["SAP"],
        red_flags=[],
        verbessern_in_anschreiben=[],
    ))
    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)

    runner = CliRunner()

    # 1. Discover
    r = runner.invoke(main, ["discover"])
    assert r.exit_code == 0, r.output
    assert "1 Sucheinträge" in r.output or "1 Suche" in r.output

    state = load_state(workspace / "bewerber" / "state.json")
    assert "arbeitsagentur-10001-1003091744-S" in state.jobs
    job = state.jobs["arbeitsagentur-10001-1003091744-S"]
    assert job.scoring.fit_score == 9
    assert job.status == JobStatus.DISCOVERED

    # 2. Mark as applied with link
    r = runner.invoke(main, [
        "mark", "arbeitsagentur-10001-1003091744-S", "applied",
        "--link", "https://applied.example/app123",
    ])
    assert r.exit_code == 0, r.output
    state = load_state(workspace / "bewerber" / "state.json")
    assert state.jobs["arbeitsagentur-10001-1003091744-S"].status == JobStatus.APPLIED
    assert state.jobs["arbeitsagentur-10001-1003091744-S"].application_link == "https://applied.example/app123"

    # 3. Add a note
    r = runner.invoke(main, ["note", "arbeitsagentur-10001-1003091744-S", "Recruiter heute angerufen, Termin am 19.06."])
    assert r.exit_code == 0

    # 4. Regen dashboard
    r = runner.invoke(main, ["regen"])
    assert r.exit_code == 0
    dash = (workspace / "bewerber" / "dashboard.html").read_text(encoding="utf-8")
    assert "Business AI Consultant" in dash
    assert "2b AHEAD" in dash
    assert "applied" in dash
    assert "Recruiter heute" in dash
    assert "https://applied.example/app123" in dash
