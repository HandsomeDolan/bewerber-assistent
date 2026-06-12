import json
import yaml
from pathlib import Path
from bewerber.tailoring.orchestrator import tailor, TailorInput, TailorResult
from bewerber.tailoring.customize import (
    CustomizedResume, CustomBerufserfahrung, ProjekterfahrungBlock, SkillKategorien,
)
from bewerber.tailoring.anschreiben import AnschreibenContent
from bewerber.shared.profile_schema import (
    MasterProfile, Person, Berufserfahrung,
)


def _write_master(tmp_path: Path) -> Path:
    profile = MasterProfile(
        person=Person(name="Steve Eigenwillig", email="s@x.de"),
        berufsprofil="Profil.",
        zielposition=[],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01"),
        ],
    )
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml.safe_dump(profile.model_dump(), allow_unicode=True))
    return path


def test_tailor_full_pipeline_with_text_input(tmp_path, mocker, monkeypatch):
    workspace = tmp_path / "ws"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = tmp_path / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    master_path = bewerber_dir / "master_profile.yaml"
    master_path.write_text(_write_master(bewerber_dir).read_text())

    # Mock LLM passes
    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="Tailored profil.",
        berufserfahrung=[CustomBerufserfahrung(
            position="PM", firma="Acme", von="2020-01", bis=None,
            werdegang_bullets=["bullet"],
            projekterfahrung=[],
        )],
        skills_kategorisiert=SkillKategorien(automatisierung_ki=["Python"]),
    ))
    mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="Sehr geehrte Damen und Herren,",
        einleitung="E.", hauptteil="H.", schluss="S.",
        gruss="Mit freundlichen Grüßen\nSteve",
    ))

    job_text = "KI Manager bei BMW. Python gesucht."
    result = tailor(TailorInput(
        posting_text=job_text,
        firma="BMW Group",
        rolle="KI Manager",
        datum="2026-06-12",
        kontakt_name=None,
        source_url=None,
        snapshot_dir=None,
        llm=mocker.Mock(),
    ))

    assert isinstance(result, TailorResult)
    out_dir = result.output_dir
    assert out_dir.name == "2026-06-12_BMW-Group_KI-Manager"
    assert (out_dir / "lebenslauf.pdf").is_file()
    assert (out_dir / "lebenslauf.html").is_file()
    assert (out_dir / "anschreiben.pdf").is_file()
    assert (out_dir / "anschreiben.md").is_file()
    assert (out_dir / "tailoring_log.json").is_file()
    assert (out_dir / "posting_meta.yaml").is_file()
    assert (out_dir / "posting.txt").is_file()

    # Audit log content
    log = json.loads((out_dir / "tailoring_log.json").read_text())
    assert log["firma"] == "BMW Group"
    assert log["rolle"] == "KI Manager"
    assert "customized" in log
    assert "anschreiben" in log

    # Posting meta has the URL field even when None
    meta = yaml.safe_load((out_dir / "posting_meta.yaml").read_text())
    assert meta["firma"] == "BMW Group"
    assert meta["source_url"] is None


def test_tailor_loads_anschreiben_few_shot_examples(tmp_path, mocker, monkeypatch):
    workspace = tmp_path / "ws"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = tmp_path / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    examples = bewerber_dir / "anschreiben_examples"
    examples.mkdir()
    (examples / "01_x.txt").write_text("Beispiel-Anschreiben.")

    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    _write_master(bewerber_dir).rename(bewerber_dir / "master_profile.yaml")

    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="x", berufserfahrung=[], skills_kategorisiert=SkillKategorien(),
    ))
    gen = mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="x", einleitung="x", hauptteil="x", schluss="x", gruss="x",
    ))

    tailor(TailorInput(
        posting_text="job", firma="X", rolle="Y", datum="2026-06-12",
        kontakt_name=None, source_url=None, snapshot_dir=None, llm=mocker.Mock(),
    ))

    # Verify few_shot_examples was passed
    args, kwargs = gen.call_args
    assert kwargs["few_shot_examples"] == ["Beispiel-Anschreiben."]


from bewerber.tailoring.orchestrator import rebuild_pdfs


def test_rebuild_pdfs_from_edited_html_and_md(tmp_path):
    out_dir = tmp_path / "2026-06-12_BMW_KI"
    out_dir.mkdir()
    (out_dir / "lebenslauf.html").write_text(
        "<!DOCTYPE html><html><body><h1>Manually edited CV</h1></body></html>",
        encoding="utf-8",
    )
    (out_dir / "anschreiben.md").write_text("# Edited\n\nManuell editiert.\n")
    (out_dir / "posting_meta.yaml").write_text(
        "firma: BMW\nrolle: KI Manager\ndatum: '2026-06-12'\nkontakt_name: null\nsource_url: null\n"
    )

    rebuild_pdfs(out_dir)

    pdf_l = (out_dir / "lebenslauf.pdf").read_bytes()
    pdf_a = (out_dir / "anschreiben.pdf").read_bytes()
    assert pdf_l.startswith(b"%PDF")
    assert pdf_a.startswith(b"%PDF")

    import pdfplumber, io
    with pdfplumber.open(io.BytesIO(pdf_l)) as p:
        lt = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "Manually edited CV" in lt
    with pdfplumber.open(io.BytesIO(pdf_a)) as p:
        at = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "Manuell editiert" in at


def test_tailor_writes_state_entry(tmp_path, monkeypatch, mocker):
    """After tailor() succeeds, state.json must contain a TrackedJob with status=TAILORED."""
    workspace = tmp_path / "ws"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = tmp_path / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    _write_master(bewerber_dir).rename(bewerber_dir / "master_profile.yaml")

    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="x", berufserfahrung=[], skills_kategorisiert=SkillKategorien(),
    ))
    mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="x", einleitung="x", hauptteil="x", schluss="x", gruss="x",
    ))

    result = tailor(TailorInput(
        posting_text="job",
        firma="2b AHEAD",
        rolle="Business AI Consultant",
        datum="2026-06-12",
        kontakt_name="Frau Moser",
        source_url="https://example.com/job/abc",
        snapshot_dir=None,
        llm=mocker.Mock(),
    ))

    from bewerber.shared.state import load_state
    from bewerber.shared.state_schema import JobStatus

    state = load_state(workspace / "bewerber" / "state.json")
    # job_id should be derived from source URL when there is no scraper external_id
    matching = [j for j in state.jobs.values() if j.raw.company == "2b AHEAD"]
    assert len(matching) == 1
    job = matching[0]
    assert job.status == JobStatus.TAILORED
    assert job.raw.title.startswith("Business AI Consultant")
    assert job.tailored_dir == str(result.output_dir)
    assert job.raw.url == "https://example.com/job/abc"


def test_tailor_updates_existing_state_entry_if_url_matches(tmp_path, monkeypatch, mocker):
    """When a job already exists in state matching source_url, tailor updates it instead of creating duplicate."""
    workspace = tmp_path / "ws"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = tmp_path / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    _write_master(bewerber_dir).rename(bewerber_dir / "master_profile.yaml")

    # Pre-seed state.json with a discovered job from Arbeitsagentur with the same URL
    from bewerber.shared.state import save_state
    from bewerber.shared.state_schema import (
        BewerberState, RawJob, TrackedJob, JobStatus, Scoring,
    )
    pre = TrackedJob(
        raw=RawJob(
            board="arbeitsagentur", external_id="10001-XYZ",
            url="https://example.com/job/abc",
            title="Old title", company="Old company", location="Leipzig",
        ),
        scoring=Scoring(
            fit_score=8, begruendung="ok", matched_skills=["n8n"],
            missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
        ),
        status=JobStatus.DISCOVERED,
    )
    pre_state = BewerberState(jobs={"arbeitsagentur-10001-XYZ": pre})
    save_state(workspace / "bewerber" / "state.json", pre_state)

    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="x", berufserfahrung=[], skills_kategorisiert=SkillKategorien(),
    ))
    mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="x", einleitung="x", hauptteil="x", schluss="x", gruss="x",
    ))

    tailor(TailorInput(
        posting_text="job",
        firma="2b AHEAD",
        rolle="Business AI Consultant",
        datum="2026-06-12",
        kontakt_name=None,
        source_url="https://example.com/job/abc",
        snapshot_dir=None,
        llm=mocker.Mock(),
    ))

    from bewerber.shared.state import load_state
    state = load_state(workspace / "bewerber" / "state.json")
    # The existing arbeitsagentur job should be the only entry, now with status=TAILORED
    assert len(state.jobs) == 1
    job = list(state.jobs.values())[0]
    assert job.status == JobStatus.TAILORED
    assert job.tailored_dir
    # Original scoring preserved
    assert job.scoring.fit_score == 8
    assert "n8n" in job.scoring.matched_skills
