import yaml
from pathlib import Path
from bewerber.profile.sync import sync_projects_into_profile, parse_profile_md


def _make_md(tmp_path: Path, name: str, body_dict: dict) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    fm = "\n".join(f"{k}: {v}" for k, v in body_dict.items())
    body = """## Kurzbeschreibung
Eine Beschreibung.

## Meine Rolle / Beitrag
Hauptentwickler.

## Fachliche Skills
- Python
- n8n

## Methodische Skills
- Agile

## Erfolge / Outcomes
- Erfolg X

## Notizen (nicht im Lebenslauf)
private kram
"""
    (folder / "_profile.md").write_text(f"---\n{fm}\n---\n{body}")
    return folder


def test_parse_profile_md(tmp_path):
    folder = _make_md(tmp_path, "1 Test", {"id": "1-test", "titel": "Test", "sichtbar_in_lebenslauf": True})
    project = parse_profile_md(folder / "_profile.md")
    assert project.id == "1-test"
    assert project.titel == "Test"
    assert project.sichtbar_in_lebenslauf is True
    assert project.kurzbeschreibung == "Eine Beschreibung."
    assert project.rolle == "Hauptentwickler."
    assert "Python" in project.skills_fachlich
    assert "Agile" in project.skills_methodisch
    assert "Erfolg X" in project.erfolge


def test_sync_creates_master_yaml_with_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path / "workspace"))
    (tmp_path / "workspace" / "bewerber").mkdir(parents=True)

    _make_md(tmp_path, "1 Alpha", {"id": "1-alpha", "titel": "Alpha", "sichtbar_in_lebenslauf": True})
    _make_md(tmp_path, "2 Beta", {"id": "2-beta", "titel": "Beta", "sichtbar_in_lebenslauf": False})
    (tmp_path / "ignored.txt").touch()

    # Pre-existing master YAML with non-project sections
    master_path = tmp_path / "workspace" / "bewerber" / "master_profile.yaml"
    master_path.write_text(yaml.safe_dump({
        "person": {"name": "Steve", "email": "s@x.de"},
        "berufsprofil": "kurz",
        "zielposition": ["KI Manager"],
    }, allow_unicode=True))

    n = sync_projects_into_profile()
    assert n == 2

    data = yaml.safe_load(master_path.read_text())
    assert data["person"]["name"] == "Steve"  # untouched
    ids = sorted(p["id"] for p in data["projekte"])
    assert ids == ["1-alpha", "2-beta"]
    alpha = next(p for p in data["projekte"] if p["id"] == "1-alpha")
    assert alpha["quelle"].endswith("1 Alpha/_profile.md")
    assert alpha["sichtbar_in_lebenslauf"] is True
    beta = next(p for p in data["projekte"] if p["id"] == "2-beta")
    assert beta["sichtbar_in_lebenslauf"] is False


def test_sync_creates_minimal_master_if_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path / "ws"))
    (tmp_path / "ws" / "bewerber").mkdir(parents=True)
    _make_md(tmp_path, "1 Alpha", {"id": "1-alpha", "titel": "Alpha", "sichtbar_in_lebenslauf": True})

    n = sync_projects_into_profile()
    assert n == 1

    master = tmp_path / "ws" / "bewerber" / "master_profile.yaml"
    data = yaml.safe_load(master.read_text())
    assert data["projekte"][0]["id"] == "1-alpha"
    assert data["person"]["name"] == "TODO Name"  # placeholder
