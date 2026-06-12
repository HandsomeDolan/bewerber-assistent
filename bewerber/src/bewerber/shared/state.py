import json
import os
import shutil
from pathlib import Path
from typing import Optional

from bewerber.shared.paths import Paths
from bewerber.shared.state_schema import BewerberState, TrackedJob


def load_state(path: Path) -> BewerberState:
    """Load state.json from disk. Returns empty BewerberState if file does not exist."""
    if not path.is_file():
        return BewerberState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return BewerberState.model_validate(data)


def save_state(path: Path, state: BewerberState) -> None:
    """Atomic save: backup existing → write to temp → rename to target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


# Fields preserved when re-importing an already-tracked job from a fresh scrape.
_PRESERVED_FIELDS = (
    "status",
    "status_history",
    "first_seen",
    "tailored_dir",
    "application_link",
    "interview_scheduled",
    "notes",
)


def upsert_job(state: BewerberState, incoming: TrackedJob) -> TrackedJob:
    """Insert or update a job in state.

    Preserves user-curated fields (status, notes, tailored_dir, ...) on re-import.
    Returns the resulting (possibly merged) job.
    """
    existing = state.jobs.get(incoming.job_id)
    if existing is None:
        state.jobs[incoming.job_id] = incoming
        return incoming

    merged = incoming.model_copy()
    for field in _PRESERVED_FIELDS:
        setattr(merged, field, getattr(existing, field))
    # Keep best available scoring (re-score only if new posting hash differs)
    if existing.scoring is not None and incoming.raw.description_hash == existing.raw.description_hash:
        merged.scoring = existing.scoring
    state.jobs[incoming.job_id] = merged
    return merged


class StateStore:
    """Convenience wrapper using Paths().state_json."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or Paths().state_json

    def load(self) -> BewerberState:
        return load_state(self.path)

    def save(self, state: BewerberState) -> None:
        save_state(self.path, state)
