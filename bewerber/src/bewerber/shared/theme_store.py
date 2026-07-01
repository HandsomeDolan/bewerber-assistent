"""Persistenz fuer User-Themes (YAML pro Theme unter data_dir/themes/)."""
import os
import yaml
from bewerber.shared.paths import Paths
from bewerber.shared.theme import Theme


def save_theme(paths: Paths, theme: Theme) -> None:
    d = paths.themes_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{theme.id}.yaml"
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(theme.model_dump(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, p)


def load_theme(paths: Paths, theme_id: str) -> Theme | None:
    p = paths.themes_dir / f"{theme_id}.yaml"
    if not p.is_file():
        return None
    return Theme.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")) or {})


def list_themes(paths: Paths) -> list[Theme]:
    d = paths.themes_dir
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.yaml")):
        try:
            out.append(Theme.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")) or {}))
        except Exception:  # noqa: BLE001 - kaputtes Theme ueberspringen
            continue
    return out


def delete_theme(paths: Paths, theme_id: str) -> bool:
    p = paths.themes_dir / f"{theme_id}.yaml"
    if p.is_file():
        p.unlink()
        return True
    return False
