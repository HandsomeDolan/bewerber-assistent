from pathlib import Path
from bewerber.shared.paths import Paths


def test_paths_resolve_from_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    p = Paths()
    assert p.workspace == tmp_path
    assert p.bewerber_dir == tmp_path / "bewerber"
    assert p.master_profile == tmp_path / "bewerber" / "master_profile.yaml"
    assert p.documents == Path("/Users/steve/Documents")
    assert p.bewerbungsunterlagen == Path("/Users/steve/Documents/Bewerbungsunterlagen")
    assert p.bewerbungen == p.bewerbungsunterlagen / "Bewerbungen"


def test_paths_default_workspace(monkeypatch):
    monkeypatch.delenv("BEWERBER_WORKSPACE", raising=False)
    p = Paths()
    assert p.workspace == Path("/Users/steve/Documents/Bewerber_Assistent")


def test_project_folders_filter(monkeypatch, tmp_path):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 Kleinanzeigen").mkdir()
    (tmp_path / "11 MerchApp").mkdir()
    (tmp_path / "Bewerbungsunterlagen").mkdir()
    (tmp_path / "random_file.pdf").touch()
    p = Paths()
    folders = sorted(f.name for f in p.project_folders())
    assert folders == ["1 Kleinanzeigen", "11 MerchApp"]
