import json
import yaml
from pathlib import Path
from bewerber.tailoring.orchestrator import tailor, TailorInput, TailorResult
from bewerber.tailoring.customize import CustomizedResume, CustomBerufserfahrung
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
        berufserfahrung=[CustomBerufserfahrung(position="PM", firma="Acme", von="2020-01", bis=None,
                                                aufgaben=["a"], erfolge=[], skills=[])],
        projekte_hervorheben=[],
        skills_reihenfolge=["Python"],
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
        berufsprofil_zugespitzt="x", berufserfahrung=[], projekte_hervorheben=[], skills_reihenfolge=[],
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
