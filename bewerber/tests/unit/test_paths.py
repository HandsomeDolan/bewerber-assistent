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


def test_project_folders_filter_excludes_non_matching(monkeypatch, tmp_path):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 Kleinanzeigen").mkdir()
    (tmp_path / "11 MerchApp").mkdir()
    (tmp_path / "Bewerbungsunterlagen").mkdir()
    (tmp_path / "random_file.pdf").touch()
    (tmp_path / "5 fakefile.txt").touch()  # matches regex but is a file
    p = Paths()
    names = [f.name for f in p.project_folders()]
    assert "Bewerbungsunterlagen" not in names
    assert "random_file.pdf" not in names
    assert "5 fakefile.txt" not in names
    assert set(names) == {"1 Kleinanzeigen", "11 MerchApp"}


def test_project_folders_natural_numeric_sort(monkeypatch, tmp_path):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    for name in [
        "1 Kleinanzeigen",
        "2 Instagram",
        "10 DeadEnd",
        "11 MerchApp",
        "16 API Gateway",
        "16 Marketing",
        "17 Kalkulation Offline",
    ]:
        (tmp_path / name).mkdir()
    p = Paths()
    names = [f.name for f in p.project_folders()]
    assert names == [
        "1 Kleinanzeigen",
        "2 Instagram",
        "10 DeadEnd",
        "11 MerchApp",
        "16 API Gateway",
        "16 Marketing",
        "17 Kalkulation Offline",
    ]


def test_project_folders_returns_empty_when_documents_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path / "nonexistent"))
    p = Paths()
    assert p.project_folders() == []


def test_project_folders_accepts_underscore_separator(monkeypatch, tmp_path):
    """Folders may use either `5 DeadEnd` (space) or `20_SEO_AFM` (underscore) as separator."""
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    for name in [
        "5 DeadEnd",
        "16 API Gateway",
        "16_Marketing",
        "18_Projectmanagement",
        "20_SEO_AFM",
        "22_BandScoring",
    ]:
        (tmp_path / name).mkdir()
    p = Paths()
    names = [f.name for f in p.project_folders()]
    assert names == [
        "5 DeadEnd",
        "16 API Gateway",
        "16_Marketing",
        "18_Projectmanagement",
        "20_SEO_AFM",
        "22_BandScoring",
    ]
