"""Central attachment management for Bewerbungen.

Loads `anlagen.yaml` (Zeugnisse, Urkunden etc.) and copies the listed files
into every newly-tailored Bewerbungsordner. The same labels are passed to the
Anschreiben renderer so the Anlagen-block of the cover letter stays in sync
with what is physically attached.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class Anlage(BaseModel):
    """A single attachment item shown once in the Anschreiben.

    `files` can be one or more PDFs that share the same label
    (e.g. Technikerzeugnis pages 1+2 → one label, two files).
    """
    label: str
    files: list[Path] = Field(default_factory=list)


class AnlagenConfig(BaseModel):
    anlagen: list[Anlage] = Field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        return [a.label for a in self.anlagen]


def load_anlagen(path: Path) -> AnlagenConfig:
    """Load anlagen.yaml. Missing file → empty config (graceful degradation)."""
    if not path.is_file():
        return AnlagenConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AnlagenConfig(**data)


def copy_anlagen_to(
    cfg: AnlagenConfig,
    target_dir: Path,
    *,
    skip_missing: bool = True,
    base_dir: Path | None = None,
) -> list[str]:
    """Copy all configured files into `target_dir`.

    Relative `Anlage.files` paths are resolved against `base_dir` (the user's
    data dir); absolute paths are used as-is. Returns source paths that could
    not be copied (only when `skip_missing=True`).
    """
    missing: list[str] = []
    for anlage in cfg.anlagen:
        for src in anlage.files:
            src = Path(src)
            if not src.is_absolute() and base_dir is not None:
                src = base_dir / src
            if not src.is_file():
                msg = f"Anlage missing on disk: {src} (label={anlage.label!r})"
                if skip_missing:
                    log.warning(msg)
                    missing.append(str(src))
                    continue
                raise FileNotFoundError(msg)
            shutil.copy2(src, target_dir / src.name)
    return missing
