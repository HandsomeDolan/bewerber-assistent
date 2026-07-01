"""Persistenz fuer User-Themes (YAML pro Theme unter data_dir/themes/)."""
import os
import re
import yaml
from bewerber.shared.paths import Paths
from bewerber.shared.theme import Theme
from bewerber.shared.slug import slug_part

RESERVED = {"classic", "modern", "base"}

_ID_RE = re.compile(r"[a-z0-9-]+")


def reserved_or_slug(name: str, existing_ids: set[str]) -> str | None:
    """Name -> eindeutiger Slug (lowercase). None, wenn leer oder mit reservierter id kollidierend."""
    base = slug_part((name or "").strip()).lower()
    if not base or base in RESERVED:
        return None
    if base not in existing_ids:
        return base
    i = 2
    while f"{base}-{i}" in existing_ids:
        i += 1
    return f"{base}-{i}"


def save_theme(paths: Paths, theme: Theme) -> None:
    if not _ID_RE.fullmatch(theme.id or ""):
        raise ValueError(f"Ungueltige Theme-id: {theme.id!r}")
    d = paths.themes_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{theme.id}.yaml"
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(theme.model_dump(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, p)


def load_theme(paths: Paths, theme_id: str) -> Theme | None:
    if not _ID_RE.fullmatch(theme_id or ""):
        return None
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
    if not _ID_RE.fullmatch(theme_id or ""):
        return False
    p = paths.themes_dir / f"{theme_id}.yaml"
    if p.is_file():
        p.unlink()
        return True
    return False
