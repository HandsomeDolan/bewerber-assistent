"""Idempotente Migration vom Single-User- ins Multi-User-Layout."""
import json
import shutil
from pathlib import Path
import yaml

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


def migrate_anlagen(workspace: Path, username: str) -> dict:
    """Kopiert in anlagen.yaml referenzierte absolute Dateien nach
    users/<username>/anlagen/ und schreibt die YAML auf relative Pfade um.
    Idempotent: bereits relative Eintraege werden uebersprungen."""
    user_dir = workspace / "bewerber" / "users" / username
    anlagen_yaml = user_dir / "anlagen.yaml"
    report = {"copied": 0, "rewritten": 0}
    if not anlagen_yaml.is_file():
        return report
    data = yaml.safe_load(anlagen_yaml.read_text(encoding="utf-8")) or {}
    anlagen = data.get("anlagen", [])
    dest_dir = user_dir / "anlagen"
    changed = False
    for anlage in anlagen:
        new_files = []
        for f in anlage.get("files", []):
            p = Path(f)
            if not p.is_absolute():
                new_files.append(f)  # bereits relativ
                continue
            if p.is_file():
                dest_dir.mkdir(parents=True, exist_ok=True)
                target = dest_dir / p.name
                if not target.exists():
                    shutil.copy2(p, target)
                report["copied"] += 1
                new_files.append(f"anlagen/{p.name}")
                changed = True
            else:
                new_files.append(f)  # Quelle fehlt -> unveraendert lassen
        anlage["files"] = new_files
    if changed:
        report["rewritten"] = 1
        tmp = anlagen_yaml.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        tmp.replace(anlagen_yaml)
    return report
