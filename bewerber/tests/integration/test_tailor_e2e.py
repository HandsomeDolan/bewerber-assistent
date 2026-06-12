import io
import yaml
from pathlib import Path
from click.testing import CliRunner
import pdfplumber

from bewerber.cli import main
from bewerber.shared.profile_schema import (
    MasterProfile, Person, Berufserfahrung, Ausbildung, Sprache, Zertifikat, Project,
)
from bewerber.tailoring.customize import CustomizedResume, CustomBerufserfahrung
from bewerber.tailoring.anschreiben import AnschreibenContent


def test_full_tailor_workflow(tmp_path, monkeypatch, mocker):
    workspace = tmp_path / "Bewerber_Assistent"
    documents = tmp_path
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = documents / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(documents))

    # Master profile with realistic data
    profile = MasterProfile(
        person=Person(name="Steve Eigenwillig", email="s.eigenwillig@yahoo.de",
                      phone="+49 1735808126", adresse="Flemmingstr. 4, Leipzig"),
        berufsprofil="Erfahrener Projekt- und Prozessmanager.",
        zielposition=["KI Manager"],
        ausbildung=[Ausbildung(art="Schule", institution="RHS Chemnitz",
                                abschluss="Techniker Maschinenbau", jahr="2015")],
        berufserfahrung=[
            Berufserfahrung(position="Vertriebsleiter", firma="Magna Glaskeramik GmbH",
                            von="2020-10", bis="2024-08", aufgaben=["Team führen"],
                            erfolge=["Umsatzsteigerung 10%"], skills=["CRM"]),
        ],
        projekte=[
            Project(id="8-n8n-builder", titel="n8n Builder",
                    kurzbeschreibung="Workflow-Automatisierung.",
                    rolle="Konzeption + Implementierung",
                    skills_fachlich=["n8n", "Python"], sichtbar_in_lebenslauf=True),
        ],
        zertifikate=[Zertifikat(name="REFA", aussteller="REFA")],
        sprachen=[Sprache(sprache="Deutsch", niveau="C2"),
                  Sprache(sprache="Englisch", niveau="B2")],
    )
    (bewerber_dir / "master_profile.yaml").write_text(
        yaml.safe_dump(profile.model_dump(), allow_unicode=True),
        encoding="utf-8",
    )

    # Posting file
    posting_file = tmp_path / "posting.txt"
    posting_file.write_text(
        "KI Manager (m/w/d) bei BMW Group, München.\n"
        "Verantwortung: KI-Roadmap, Cross-functional Teams.\n"
        "Anforderungen: Projekterfahrung, Python-Grundlagen.\n"
    )

    # Mock LLM at orchestrator
    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="Erfahrener Projektmanager mit KI-Automatisierungsschwerpunkt.",
        berufserfahrung=[CustomBerufserfahrung(
            position="Vertriebsleiter & Projektmanager",
            firma="Magna Glaskeramik GmbH",
            von="2020-10", bis="2024-08",
            aufgaben=["Internationales Team führen", "CRM-Einführung"],
            erfolge=["Umsatz +10%, Lead-Transparenz +20%"],
            skills=["Team-Führung", "CRM"],
        )],
        projekte_hervorheben=["8-n8n-builder"],
        skills_reihenfolge=["Projektmanagement", "n8n", "Python", "KI-Automatisierung"],
    ))
    mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="Sehr geehrte Damen und Herren,",
        einleitung="Mit großem Interesse habe ich Ihre Ausschreibung gelesen.",
        hauptteil="Meine Erfahrung als Projektmanager bei Magna sowie meine "
                  "praktische Arbeit mit n8n-Workflows passen zur KI-Manager-Rolle.",
        schluss="Über die Einladung zum Gespräch würde ich mich sehr freuen.",
        gruss="Mit freundlichen Grüßen\nSteve Eigenwillig",
    ))
    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)

    runner = CliRunner()
    result = runner.invoke(main, [
        "tailor",
        "--posting-file", str(posting_file),
        "--firma", "BMW Group",
        "--rolle", "KI Manager",
        "--datum", "2026-06-12",
    ])
    assert result.exit_code == 0, result.output

    out_dir = bu / "Bewerbungen" / "2026-06-12_BMW-Group_KI-Manager"
    assert out_dir.is_dir()

    # All expected artifacts exist
    for name in ("lebenslauf.pdf", "lebenslauf.html", "anschreiben.pdf",
                 "anschreiben.md", "posting.txt", "posting_meta.yaml",
                 "tailoring_log.json"):
        assert (out_dir / name).is_file(), f"missing: {name}"

    # PDFs contain expected text
    with pdfplumber.open(io.BytesIO((out_dir / "lebenslauf.pdf").read_bytes())) as p:
        cv_text = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "Steve Eigenwillig" in cv_text
    assert "Magna" in cv_text
    assert "n8n Builder" in cv_text
    assert "KI-Automatisierung" in cv_text or "Automatisierung" in cv_text

    with pdfplumber.open(io.BytesIO((out_dir / "anschreiben.pdf").read_bytes())) as p:
        ans_text = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "BMW Group" in ans_text
    assert "Bewerbung als KI Manager" in ans_text
    assert "Sehr geehrte Damen und Herren" in ans_text
    assert "Mit freundlichen Grüßen" in ans_text
