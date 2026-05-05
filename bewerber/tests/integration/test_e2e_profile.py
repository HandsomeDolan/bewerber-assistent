import yaml
from pathlib import Path
from click.testing import CliRunner

from bewerber.cli import main
from bewerber.shared.profile_schema import (
    MasterProfile,
    Person,
    Ausbildung,
    Berufserfahrung,
    Zertifikat,
    Sprache,
)
from bewerber.profile.extractor import ExtractedProfile
from bewerber.profile.projects import ProjectDraft


def test_full_profile_workflow(tmp_path, monkeypatch, mocker):
    # Layout
    workspace = tmp_path / "Bewerber_Assistent"
    documents = tmp_path
    (workspace / "bewerber").mkdir(parents=True)
    bu = documents / "Bewerbungsunterlagen"
    bu.mkdir()
    (bu / "Lebenslauf.pdf").write_bytes(b"x")
    bu_bewerbungen = bu / "Bewerbungen"
    bu_bewerbungen.mkdir()

    p1 = documents / "1 Kleinanzeigen"
    p1.mkdir()
    (p1 / "README.md").write_text("# Kleinanzeigen\nMarketplace bot.")
    p2 = documents / "8 n8n_builder"
    p2.mkdir()
    (p2 / "README.md").write_text("# n8n Builder\nWorkflow tool.")

    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(documents))

    # Mock LLM at extractor + project layer
    monkeypatch.setattr(
        "bewerber.cli.extract_profile_from_documents",
        lambda d, llm: ExtractedProfile(
            person=Person(name="Steve", email="s@x.de"),
            berufsprofil="profil",
            zielposition=["KI Manager"],
            ausbildung=[Ausbildung(art="Techniker", institution="X")],
            berufserfahrung=[
                Berufserfahrung(position="PM", firma="Acme", von="2020-01", bis=None)
            ],
            zertifikate=[Zertifikat(name="REFA")],
            sprachen=[Sprache(sprache="Deutsch", niveau="Muttersprache")],
            interessen=[],
        ),
    )
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ProjectDraft(
        kurzbeschreibung="Beschreibung.",
        rolle="Entwickler.",
        skills_fachlich=["Python"],
        skills_methodisch=["Agile"],
        erfolge=[],
    )
    monkeypatch.setattr("bewerber.cli.LLMClient", lambda: fake_llm)

    runner = CliRunner()

    # 1. profile init (no anschreiben selected)
    result = runner.invoke(main, ["profile", "init"], input="\n")
    assert result.exit_code == 0, result.output

    # 2. projects scan
    result = runner.invoke(main, ["projects", "scan"])
    assert result.exit_code == 0, result.output
    assert (p1 / "_profile.md").is_file()
    assert (p2 / "_profile.md").is_file()

    # 3. profile sync
    result = runner.invoke(main, ["profile", "sync"])
    assert result.exit_code == 0, result.output
    assert "2" in result.output

    # Validate the resulting master YAML
    master = workspace / "bewerber" / "master_profile.yaml"
    data = yaml.safe_load(master.read_text())
    profile = MasterProfile(**data)
    assert profile.person.name == "Steve"
    assert len(profile.projekte) == 2
    project_ids = sorted(p.id for p in profile.projekte)
    assert project_ids == ["1-kleinanzeigen", "8-n8n-builder"]
    assert profile.berufserfahrung[0].firma == "Acme"
