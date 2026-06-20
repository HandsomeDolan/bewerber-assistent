"""Idempotente Migration vom Single-User- ins Multi-User-Layout."""
import json
import shutil
from pathlib import Path

_DATA_FILES = ("master_profile.yaml", "state.json", "state.json.bak",
               "searches.yaml", "anlagen.yaml")


def migrate_to_multiuser(workspace: Path, documents: Path, username: str) -> dict:
    bewerber_dir = workspace / "bewerber"
    user_dir = bewerber_dir / "users" / username
    user_bew = user_dir / "Bewerbungen"
    user_dir.mkdir(parents=True, exist_ok=True)
    user_bew.mkdir(parents=True, exist_ok=True)

    report = {"moved_files": [], "moved_dirs": [], "rewritten_paths": 0}

    # 1) Datendateien verschieben (nur wenn noch am alten Ort)
    for name in _DATA_FILES:
        src = bewerber_dir / name
        dst = user_dir / name
        if src.is_file() and not dst.exists():
            shutil.move(str(src), str(dst))
            report["moved_files"].append(name)

    # 2) Bestehende Bewerbungs-Ordner verschieben
    old_bew = documents / "Bewerbungsunterlagen" / "Bewerbungen"
    if old_bew.is_dir():
        for entry in list(old_bew.iterdir()):
            if entry.is_dir():
                target = user_bew / entry.name
                if not target.exists():
                    shutil.move(str(entry), str(target))
                    report["moved_dirs"].append(entry.name)

    # 3) tailored_dir-Pfade in state.json umschreiben (Basename -> neuer User-Bewerbungen-Ordner)
    state_path = user_dir / "state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        changed = False
        for job in state.get("jobs", {}).values():
            td = job.get("tailored_dir")
            if td:
                new_td = str(user_bew / Path(td).name)
                if new_td != td:
                    job["tailored_dir"] = new_td
                    changed = True
                    report["rewritten_paths"] += 1
        if changed:
            tmp = state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(state_path)

    return report
