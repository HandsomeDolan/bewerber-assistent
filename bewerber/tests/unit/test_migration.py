import json
from pathlib import Path

from bewerber.migration import migrate_to_multiuser


def _seed_legacy(workspace: Path, documents: Path):
    bw = workspace / "bewerber"
    bw.mkdir(parents=True)
    (bw / "master_profile.yaml").write_text("person: {name: Steve}\n")
    (bw / "searches.yaml").write_text("searches: []\n")
    (bw / "anlagen.yaml").write_text("anlagen: []\n")
    # state.json mit einem Job, dessen tailored_dir auf alten Absolutpfad zeigt
    old_bew = documents / "Bewerbungsunterlagen" / "Bewerbungen"
    job_dir = old_bew / "2026-06-12_Acme_Consultant"
    job_dir.mkdir(parents=True)
    (job_dir / "cv.pdf").write_text("PDF")
    state = {"jobs": {"arbeitsagentur-x1": {
        "raw": {"board": "arbeitsagentur", "external_id": "x1", "url": "u",
                "title": "t", "company": "Acme", "location": "L"},
        "tailored_dir": str(job_dir),
    }}, "failed_urls": []}
    (bw / "state.json").write_text(json.dumps(state))


def test_migration_moves_data_and_rewrites_paths(tmp_path):
    workspace = tmp_path / "ws"
    documents = tmp_path / "docs"
    _seed_legacy(workspace, documents)

    report = migrate_to_multiuser(workspace, documents, "seigenwillig")

    user_dir = workspace / "bewerber" / "users" / "seigenwillig"
    assert (user_dir / "master_profile.yaml").is_file()
    assert (user_dir / "searches.yaml").is_file()
    assert (user_dir / "state.json").is_file()
    # Bewerbungsordner verschoben
    assert (user_dir / "Bewerbungen" / "2026-06-12_Acme_Consultant" / "cv.pdf").is_file()
    # tailored_dir umgeschrieben
    state = json.loads((user_dir / "state.json").read_text())
    new_td = state["jobs"]["arbeitsagentur-x1"]["tailored_dir"]
    assert new_td == str(user_dir / "Bewerbungen" / "2026-06-12_Acme_Consultant")
    # Alte Dateien weg
    assert not (workspace / "bewerber" / "master_profile.yaml").exists()


def test_migration_is_idempotent(tmp_path):
    workspace = tmp_path / "ws"
    documents = tmp_path / "docs"
    _seed_legacy(workspace, documents)
    migrate_to_multiuser(workspace, documents, "seigenwillig")
    # Zweiter Lauf darf nicht crashen und nichts kaputt machen
    report2 = migrate_to_multiuser(workspace, documents, "seigenwillig")
    assert report2["moved_files"] == []
    user_dir = workspace / "bewerber" / "users" / "seigenwillig"
    assert (user_dir / "master_profile.yaml").is_file()


def test_migrate_anlagen_copies_and_rewrites(tmp_path):
    import yaml
    from bewerber.migration import migrate_anlagen
    workspace = tmp_path / "ws"
    user_dir = workspace / "bewerber" / "users" / "u1"
    user_dir.mkdir(parents=True)
    # Externe Quelldatei (absoluter Pfad), wie nach rsync auf dem Pi vorhanden
    src = tmp_path / "Allgemeine Dokumente" / "REFA.pdf"
    src.parent.mkdir(parents=True)
    src.write_text("PDF")
    (user_dir / "anlagen.yaml").write_text(
        yaml.safe_dump({"anlagen": [{"label": "REFA", "files": [str(src)]}]}),
    )
    report = migrate_anlagen(workspace, "u1")
    assert report["copied"] == 1
    assert (user_dir / "anlagen" / "REFA.pdf").is_file()
    cfg = yaml.safe_load((user_dir / "anlagen.yaml").read_text())
    assert cfg["anlagen"][0]["files"] == ["anlagen/REFA.pdf"]


def test_migrate_anlagen_idempotent(tmp_path):
    import yaml
    from bewerber.migration import migrate_anlagen
    workspace = tmp_path / "ws"
    user_dir = workspace / "bewerber" / "users" / "u1"
    user_dir.mkdir(parents=True)
    src = tmp_path / "doc.pdf"; src.write_text("PDF")
    (user_dir / "anlagen.yaml").write_text(
        yaml.safe_dump({"anlagen": [{"label": "D", "files": [str(src)]}]}),
    )
    migrate_anlagen(workspace, "u1")
    report2 = migrate_anlagen(workspace, "u1")
    assert report2["copied"] == 0  # bereits relativ -> nichts mehr zu tun
