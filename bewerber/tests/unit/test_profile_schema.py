import pytest
import yaml
from pydantic import ValidationError
from bewerber.shared.profile_schema import MasterProfile, Project, Berufserfahrung


def test_minimal_valid_profile():
    data = {
        "person": {"name": "Steve Eigenwillig", "email": "s@example.com"},
        "berufsprofil": "Erfahrener Projektmanager mit Fokus auf KI-Automatisierung.",
        "zielposition": ["KI Manager", "Lead Projektmanager"],
        "ausbildung": [],
        "berufserfahrung": [],
        "projekte": [],
    }
    profile = MasterProfile(**data)
    assert profile.person.name == "Steve Eigenwillig"
    assert "KI Manager" in profile.zielposition


def test_project_requires_id_and_titel():
    with pytest.raises(ValidationError):
        Project(titel="x")  # id missing


def test_project_arbeitgeber_is_optional_and_defaults_none():
    p = Project(id="x", titel="y")
    assert p.arbeitgeber is None


def test_project_arbeitgeber_accepts_string():
    p = Project(id="x", titel="y", arbeitgeber="IC Music and Apparel GmbH")
    assert p.arbeitgeber == "IC Music and Apparel GmbH"


def test_berufserfahrung_bis_optional():
    job = Berufserfahrung(
        position="PM",
        firma="Acme",
        von="2020-03",
        bis=None,
        aufgaben=[],
        erfolge=[],
        skills=[],
    )
    assert job.bis is None


def test_yaml_roundtrip(tmp_path):
    data = {
        "person": {"name": "X", "email": "x@y.de"},
        "berufsprofil": "kurz",
        "zielposition": ["A"],
        "ausbildung": [],
        "berufserfahrung": [],
        "projekte": [
            {
                "id": "8-n8n-builder",
                "titel": "n8n Builder",
                "kurzbeschreibung": "k",
                "rolle": "r",
                "skills_fachlich": ["Python"],
                "skills_methodisch": [],
                "sichtbar_in_lebenslauf": True,
            }
        ],
    }
    profile = MasterProfile(**data)
    f = tmp_path / "p.yaml"
    f.write_text(yaml.safe_dump(profile.model_dump(), allow_unicode=True))
    loaded = MasterProfile(**yaml.safe_load(f.read_text()))
    assert loaded.projekte[0].id == "8-n8n-builder"
