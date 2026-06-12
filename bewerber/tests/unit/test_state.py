import json
from pathlib import Path
from bewerber.shared.state import (
    StateStore, load_state, save_state, upsert_job,
)
from bewerber.shared.state_schema import (
    BewerberState, RawJob, TrackedJob, JobStatus,
)


def _make_raw(board="arbeitsagentur", ext_id="x1") -> RawJob:
    return RawJob(
        board=board, external_id=ext_id,
        url=f"https://{board}/{ext_id}",
        title="KI Manager",
        company="Acme",
        location="Leipzig",
    )


def test_load_state_returns_empty_when_missing(tmp_path):
    p = tmp_path / "state.json"
    state = load_state(p)
    assert isinstance(state, BewerberState)
    assert state.jobs == {}
    assert state.schema_version == 1


def test_save_then_load_round_trip(tmp_path):
    state = BewerberState(jobs={"arbeitsagentur-x1": TrackedJob(raw=_make_raw())})
    p = tmp_path / "state.json"
    save_state(p, state)
    loaded = load_state(p)
    assert loaded.jobs["arbeitsagentur-x1"].raw.title == "KI Manager"


def test_save_writes_backup_of_prior_state(tmp_path):
    p = tmp_path / "state.json"
    s1 = BewerberState(jobs={"a-1": TrackedJob(raw=_make_raw("a", "1"))})
    save_state(p, s1)
    s2 = BewerberState(jobs={"a-2": TrackedJob(raw=_make_raw("a", "2"))})
    save_state(p, s2)
    bak = p.with_suffix(".json.bak")
    assert bak.is_file()
    bak_data = json.loads(bak.read_text())
    assert "a-1" in bak_data["jobs"]
    current = json.loads(p.read_text())
    assert "a-2" in current["jobs"]


def test_save_is_atomic(tmp_path, monkeypatch):
    """Failure during write must not leave a corrupt main file."""
    p = tmp_path / "state.json"
    save_state(p, BewerberState(jobs={"a-1": TrackedJob(raw=_make_raw("a", "1"))}))

    # Simulate failure: replace os.replace to raise
    import os
    real_replace = os.replace

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)

    try:
        save_state(p, BewerberState(jobs={"a-2": TrackedJob(raw=_make_raw("a", "2"))}))
    except OSError:
        pass

    # Restore + verify original still readable
    monkeypatch.setattr(os, "replace", real_replace)
    loaded = load_state(p)
    assert "a-1" in loaded.jobs  # still the original


def test_upsert_job_inserts_new(tmp_path):
    state = BewerberState()
    job = TrackedJob(raw=_make_raw("arbeitsagentur", "1"))
    upsert_job(state, job)
    assert "arbeitsagentur-1" in state.jobs


def test_upsert_job_preserves_status_on_existing(tmp_path):
    """Re-importing an already-tracked job must NOT overwrite status / notes / tailored_dir."""
    state = BewerberState()
    job = TrackedJob(raw=_make_raw("arbeitsagentur", "1"), status=JobStatus.APPLIED,
                     notes="Telefoniert", tailored_dir="/some/dir")
    state.jobs[job.job_id] = job

    # Same job arrives again from a scrape (status would be DISCOVERED by default)
    re_imported = TrackedJob(raw=_make_raw("arbeitsagentur", "1"))
    upsert_job(state, re_imported)

    kept = state.jobs["arbeitsagentur-1"]
    assert kept.status == JobStatus.APPLIED  # preserved
    assert kept.notes == "Telefoniert"
    assert kept.tailored_dir == "/some/dir"


def test_state_store_writes_to_paths_master(tmp_path, monkeypatch):
    """StateStore convenience wrapper uses Paths().state_json by default."""
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    (tmp_path / "bewerber").mkdir()
    store = StateStore()
    state = store.load()
    assert state.jobs == {}
    state.jobs["a-1"] = TrackedJob(raw=_make_raw("a", "1"))
    store.save(state)
    assert (tmp_path / "bewerber" / "state.json").is_file()
