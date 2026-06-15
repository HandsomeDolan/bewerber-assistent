# Plan B - Discovery + Tracking + Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Discovery (3 German job boards: Arbeitsagentur, LinkedIn DE, Indeed.de), Scoring (LLM against master_profile), Tracking (state.json with status workflow) and Static HTML Dashboard subsystems. Result: Steve runs `bewerber discover` → curated, scored job list → status tracking via CLI → static dashboard for daily use.

**Architecture:** Three discovery scrapers behind a common `BoardAdapter` protocol feed a shared `state.json` store (pydantic-validated). Each new job runs through an enrich step (full posting text) and an LLM scoring pass against the master_profile, producing a `Scoring` block with fit_score and reasoning. State mutations happen via dedicated CLI commands (`bewerber mark <id> <status>`, `bewerber note <id> "..."`); tailoring (Plan C) updates state automatically when run against a known job. A static HTML dashboard is regenerated on every state change, with inline JSON for offline client-side filtering and sorting.

**Tech Stack:** Python 3.11+, Click, pydantic v2, PyYAML, `python-jobspy>=1.1.80` (LinkedIn/Indeed), `requests` (Arbeitsagentur JSON API + enrich), `readability-lxml` (extract main content from arbitrary HTML), OpenAI structured outputs (gpt-5.1-mini), Jinja2 (dashboard template).

**Spec reference:** [docs/superpowers/specs/2026-05-04-bewerber-assistent-design.md](../specs/2026-05-04-bewerber-assistent-design.md), Subsystems 2 (Discovery) + 4 (Dashboard).

**Prerequisites:** Plans A + C complete. `master_profile.yaml` exists. `bewerber tailor` works end-to-end. 82 tests green.

---

## File Structure (Plan B)

```
bewerber/
├── pyproject.toml                                # +deps: python-jobspy, requests, readability-lxml
├── searches.yaml                                 # gitignored, user-edited config (template tracked)
├── searches.yaml.example                         # template (tracked)
├── state.json                                    # gitignored (personal data); written/read by tool
├── dashboard.html                                # gitignored (generated); regenerated on every state change
├── src/bewerber/
│   ├── cli.py                                    # +discover, mark, note, track, regen, serve commands
│   ├── shared/
│   │   ├── state.py                              # state.json I/O with atomic writes + backup
│   │   └── state_schema.py                       # pydantic models: RawJob, Scoring, JobStatus, TrackedJob, BewerberState
│   ├── discovery/                                # new package
│   │   ├── __init__.py
│   │   ├── searches.py                           # searches.yaml schema + loader
│   │   ├── scoring.py                            # LLM scoring pass against master_profile
│   │   ├── enrich.py                             # fetch full posting HTML for jobs lacking description
│   │   ├── orchestrator.py                       # discover() top-level: scrape → enrich → score → upsert
│   │   └── scrapers/
│   │       ├── __init__.py                       # BoardAdapter protocol + registry
│   │       ├── arbeitsagentur.py                 # official JSON API
│   │       ├── linkedin.py                       # via python-jobspy
│   │       └── indeed.py                         # via python-jobspy
│   └── dashboard/
│       ├── __init__.py
│       └── render.py                             # build dashboard.html from state.json
├── templates/
│   └── dashboard.html.j2                         # static HTML w/ inline state JSON + vanilla JS
└── tests/
    ├── unit/
    │   ├── test_state.py                         # I/O + backup + schema validation
    │   ├── test_state_schema.py                  # pydantic validation
    │   ├── test_searches.py                      # searches.yaml loader
    │   ├── test_scoring.py                       # LLM scoring (mocked)
    │   ├── test_enrich.py                        # enrich logic (mocked HTTP)
    │   ├── test_scraper_arbeitsagentur.py        # JSON parsing (fixture-based)
    │   ├── test_scraper_linkedin.py              # jobspy bindings (mocked)
    │   ├── test_scraper_indeed.py                # jobspy bindings (mocked)
    │   ├── test_discovery_orchestrator.py        # composition w/ mocked scrapers
    │   ├── test_dashboard.py                     # render template
    │   └── test_cli_b.py                         # CLI: discover, mark, note, track, regen
    ├── integration/
    │   └── test_discovery_e2e.py                 # full pipeline with mocked scrapers + LLM
    └── fixtures/
        ├── arbeitsagentur_response.json          # realistic JSON-API response
        ├── jobspy_linkedin_jobs.json             # fixture for mocked jobspy
        └── posting_with_full_description.html    # for enrich test
```

**Module responsibilities:**
- `state.py`: only file I/O (atomic write, backup, load with schema validation). No business logic.
- `state_schema.py`: pydantic models, JobStatus enum.
- `discovery/searches.py`: parse searches.yaml, return validated `SearchConfig`.
- `discovery/scrapers/<board>.py`: each scraper IS-A `BoardAdapter` — returns `list[RawJob]`. No state mutation.
- `discovery/enrich.py`: given `RawJob` with missing description, fetch URL and extract main text. Stateless.
- `discovery/scoring.py`: LLM pass returning `Scoring` instance for one job. No state mutation.
- `discovery/orchestrator.py`: composes scrapers → enrich → score → state upsert. Where errors are isolated per-board.
- `dashboard/render.py`: pure rendering — takes state, returns HTML bytes.
- `cli.py`: arg parsing + dispatch. Business logic lives in modules.

---

## Task 1: Plan B Dependencies

**Files:**
- Modify: `bewerber/pyproject.toml`

- [ ] **Step 1: Append new dependencies to `pyproject.toml`**

Read `bewerber/pyproject.toml`. Find the `dependencies = [...]` list under `[project]`. Append these three lines:

```toml
    "python-jobspy>=1.1.80",
    "requests>=2.31",
    "readability-lxml>=0.8.1",
```

- [ ] **Step 2: Install**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected output ends with `Successfully installed ... python-jobspy-... readability-lxml-...`.

- [ ] **Step 3: Verify imports**

```bash
python3 -c "import jobspy; import requests; from readability import Document; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/pyproject.toml
git commit -m "chore(deps): add jobspy, requests, readability-lxml for Plan B"
```

---

## Task 2: State Schema (Pydantic Models)

**Files:**
- Create: `bewerber/src/bewerber/shared/state_schema.py`
- Test: `bewerber/tests/unit/test_state_schema.py`

TDD.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_state_schema.py`:

```python
import pytest
from datetime import date
from pydantic import ValidationError
from bewerber.shared.state_schema import (
    RawJob, Scoring, JobStatus, StatusHistoryEntry, TrackedJob, BewerberState,
)


def test_jobstatus_enum_has_expected_values():
    assert JobStatus.DISCOVERED.value == "discovered"
    assert JobStatus.SHORTLISTED.value == "shortlisted"
    assert JobStatus.TAILORED.value == "tailored"
    assert JobStatus.APPLIED.value == "applied"
    assert JobStatus.INTERVIEW.value == "interview"
    assert JobStatus.OFFER.value == "offer"
    assert JobStatus.REJECTED.value == "rejected"
    assert JobStatus.WITHDRAWN.value == "withdrawn"


def test_raw_job_minimal():
    job = RawJob(
        board="arbeitsagentur",
        external_id="10001-1003091744-S",
        url="https://example.com/job/1",
        title="KI Manager",
        company="ACME",
        location="Leipzig",
    )
    assert job.posted_date is None
    assert job.description is None


def test_scoring_clamps_fit_score():
    """fit_score must be 1-10."""
    with pytest.raises(ValidationError):
        Scoring(fit_score=0, begruendung="x", matched_skills=[], missing_skills=[], red_flags=[], verbessern_in_anschreiben=[])
    with pytest.raises(ValidationError):
        Scoring(fit_score=11, begruendung="x", matched_skills=[], missing_skills=[], red_flags=[], verbessern_in_anschreiben=[])
    ok = Scoring(fit_score=8, begruendung="passt", matched_skills=["n8n"], missing_skills=[], red_flags=[], verbessern_in_anschreiben=[])
    assert ok.fit_score == 8


def test_tracked_job_id_format():
    """job_id = '<board>-<external_id>' (computed property)."""
    raw = RawJob(board="linkedin", external_id="3401234567", url="https://x",
                 title="t", company="c", location="l")
    job = TrackedJob(raw=raw)
    assert job.job_id == "linkedin-3401234567"
    assert job.status == JobStatus.DISCOVERED


def test_tracked_job_round_trip_through_json():
    raw = RawJob(board="indeed", external_id="abc123", url="https://x",
                 title="t", company="c", location="l", posted_date=date(2026, 6, 1))
    scoring = Scoring(fit_score=7, begruendung="ok", matched_skills=["a"],
                     missing_skills=["b"], red_flags=[], verbessern_in_anschreiben=[])
    job = TrackedJob(
        raw=raw, scoring=scoring, status=JobStatus.APPLIED,
        status_history=[StatusHistoryEntry(status=JobStatus.DISCOVERED, at="2026-06-12T10:00:00")],
        application_link="https://applied.example",
        notes="Telefoniert mit Frau Müller am 13.06.",
    )
    payload = job.model_dump(mode="json")
    restored = TrackedJob.model_validate(payload)
    assert restored.status == JobStatus.APPLIED
    assert restored.raw.posted_date == date(2026, 6, 1)
    assert restored.scoring.fit_score == 7


def test_bewerber_state_holds_jobs_by_id():
    raw = RawJob(board="arbeitsagentur", external_id="x1", url="u", title="t",
                 company="c", location="l")
    state = BewerberState(
        schema_version=1,
        last_discovery_run=None,
        scrape_errors={},
        jobs={"arbeitsagentur-x1": TrackedJob(raw=raw)},
    )
    assert "arbeitsagentur-x1" in state.jobs
    assert state.jobs["arbeitsagentur-x1"].status == JobStatus.DISCOVERED
```

- [ ] **Step 2: Run, verify fail**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
pytest tests/unit/test_state_schema.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/shared/state_schema.py`**

```python
from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, computed_field


class JobStatus(str, Enum):
    DISCOVERED = "discovered"
    SHORTLISTED = "shortlisted"
    TAILORED = "tailored"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class RawJob(BaseModel):
    """A job posting as fetched from a board. Description may be None until enriched."""
    model_config = ConfigDict(extra="forbid")
    board: str  # "arbeitsagentur" | "linkedin" | "indeed"
    external_id: str
    url: str
    title: str
    company: str
    location: str
    posted_date: Optional[date] = None
    description: Optional[str] = None
    description_hash: Optional[str] = None


class Scoring(BaseModel):
    """LLM scoring of a job against the master_profile."""
    model_config = ConfigDict(extra="forbid")
    fit_score: int = Field(ge=1, le=10, description="1 (kein Match) bis 10 (perfekt).")
    begruendung: str = Field(description="2-3 Sätze: warum dieser Score.")
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    verbessern_in_anschreiben: list[str] = Field(default_factory=list)


class StatusHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: JobStatus
    at: str  # ISO 8601 timestamp


class TrackedJob(BaseModel):
    """A job in state.json with optional scoring, status workflow, tailored output linkage."""
    model_config = ConfigDict(extra="forbid")
    raw: RawJob
    scoring: Optional[Scoring] = None
    status: JobStatus = JobStatus.DISCOVERED
    status_history: list[StatusHistoryEntry] = Field(default_factory=list)
    first_seen: Optional[str] = None  # ISO 8601 timestamp
    tailored_dir: Optional[str] = None  # path to Bewerbungsordner once tailored
    application_link: Optional[str] = None  # URL to the submitted application (recruiter portal etc.)
    interview_scheduled: Optional[str] = None  # ISO 8601
    notes: str = ""

    @computed_field
    @property
    def job_id(self) -> str:
        return f"{self.raw.board}-{self.raw.external_id}"


class ScrapeError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    last_error: str
    at: str  # ISO 8601


class BewerberState(BaseModel):
    """Top-level state.json contract."""
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    last_discovery_run: Optional[str] = None  # ISO 8601
    scrape_errors: dict[str, ScrapeError] = Field(default_factory=dict)
    jobs: dict[str, TrackedJob] = Field(default_factory=dict)
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_state_schema.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/shared/state_schema.py bewerber/tests/unit/test_state_schema.py
git commit -m "feat(shared): pydantic schema for state.json (RawJob, Scoring, TrackedJob, BewerberState)"
```

---

## Task 3: State I/O (Load, Save, Backup)

**Files:**
- Create: `bewerber/src/bewerber/shared/state.py`
- Test: `bewerber/tests/unit/test_state.py`

State I/O with atomic writes (temp file + rename) and pre-write backup.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_state.py`:

```python
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
    job = TrackedJob(raw=_make_raw("a", "1"))
    upsert_job(state, job)
    assert "arbeitsagentur-1" in state.jobs


def test_upsert_job_preserves_status_on_existing(tmp_path):
    """Re-importing an already-tracked job must NOT overwrite status / notes / tailored_dir."""
    state = BewerberState()
    job = TrackedJob(raw=_make_raw("a", "1"), status=JobStatus.APPLIED,
                     notes="Telefoniert", tailored_dir="/some/dir")
    state.jobs[job.job_id] = job

    # Same job arrives again from a scrape (status would be DISCOVERED by default)
    re_imported = TrackedJob(raw=_make_raw("a", "1"))
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
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_state.py -v
```

Expected: ImportError.

- [ ] **Step 3: Add `state_json` property to `Paths`**

Edit `bewerber/src/bewerber/shared/paths.py`. Find the `master_profile` property and add right below it (before `bewerbungsunterlagen`):

```python
    @property
    def state_json(self) -> Path:
        return self.bewerber_dir / "state.json"

    @property
    def dashboard_html(self) -> Path:
        return self.bewerber_dir / "dashboard.html"
```

- [ ] **Step 4: Implement `bewerber/src/bewerber/shared/state.py`**

```python
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
```

- [ ] **Step 5: Run, verify pass**

```bash
pytest tests/unit/test_state.py -v tests/unit/test_paths.py -v
```

Expected: 7 (new) + 6 (existing paths tests) all pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/shared/state.py bewerber/src/bewerber/shared/paths.py bewerber/tests/unit/test_state.py
git commit -m "feat(shared): state.py with atomic save, backup, upsert preserving user-curated fields"
```

---

## Task 4: Searches Config (searches.yaml)

**Files:**
- Create: `bewerber/searches.yaml.example`
- Create: `bewerber/src/bewerber/discovery/__init__.py` (empty)
- Create: `bewerber/src/bewerber/discovery/searches.py`
- Test: `bewerber/tests/unit/test_searches.py`

- [ ] **Step 1: Create `bewerber/searches.yaml.example`**

Write:

```yaml
# Beispiel-Konfiguration. Kopieren nach `searches.yaml` und anpassen.
defaults:
  locations: [Leipzig, Berlin, Remote]
  date_posted_max_days: 14
  min_fit_score: 6   # nur informativ - im Dashboard standardmäßig ausgeblendet

searches:
  - name: "KI Manager"
    keywords:
      - "KI Manager"
      - "AI Product Manager"
      - "KI Produktmanager"
    boards: [arbeitsagentur, linkedin, indeed]

  - name: "Lead Projektmanager"
    keywords:
      - "Lead Projektmanager"
      - "Senior Projektleiter"
      - "Projektleitung Digitalisierung"
    boards: [arbeitsagentur, linkedin]

  - name: "Generative AI / Automation"
    keywords:
      - "Generative AI Engineer"
      - "n8n Automation"
      - "LLM Engineer"
    boards: [linkedin, indeed]
```

- [ ] **Step 2: Add `searches.yaml` to root `.gitignore`**

Edit `/Users/steve/Documents/Bewerber_Assistent/.gitignore`. Find the "Personal data" section and add a new line right after `bewerber/dashboard.html`:

```
bewerber/searches.yaml
```

(Note: `.gitignore` already has personal data section from Plan A; preserve all existing entries.)

- [ ] **Step 3: Write failing test**

Write to `bewerber/tests/unit/test_searches.py`:

```python
import pytest
from pathlib import Path
from pydantic import ValidationError
from bewerber.discovery.searches import (
    SearchDefaults, SearchEntry, SearchesConfig, load_searches,
)


def test_search_entry_minimal():
    s = SearchEntry(name="KI Manager", keywords=["KI Manager"], boards=["arbeitsagentur"])
    assert s.name == "KI Manager"


def test_searches_config_rejects_unknown_board():
    with pytest.raises(ValidationError):
        SearchEntry(name="x", keywords=["a"], boards=["myspace"])


def test_load_searches_reads_yaml(tmp_path):
    p = tmp_path / "searches.yaml"
    p.write_text("""defaults:
  locations: [Leipzig]
  date_posted_max_days: 7
  min_fit_score: 5
searches:
  - name: KI Manager
    keywords: [KI Manager, AI PM]
    boards: [arbeitsagentur, linkedin]
""")
    cfg = load_searches(p)
    assert cfg.defaults.locations == ["Leipzig"]
    assert cfg.defaults.date_posted_max_days == 7
    assert len(cfg.searches) == 1
    assert cfg.searches[0].keywords == ["KI Manager", "AI PM"]


def test_load_searches_missing_file(tmp_path):
    p = tmp_path / "nope.yaml"
    with pytest.raises(FileNotFoundError):
        load_searches(p)


def test_load_searches_invalid_yaml_raises(tmp_path):
    p = tmp_path / "searches.yaml"
    p.write_text("not: valid\n  : structure")
    with pytest.raises(Exception):
        load_searches(p)
```

- [ ] **Step 4: Run, verify fail**

```bash
pytest tests/unit/test_searches.py -v
```

Expected: ImportError.

- [ ] **Step 5: Implement `bewerber/src/bewerber/discovery/__init__.py`** (empty file).

- [ ] **Step 6: Implement `bewerber/src/bewerber/discovery/searches.py`**

```python
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field, ConfigDict


VALID_BOARDS = Literal["arbeitsagentur", "linkedin", "indeed"]


class SearchDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locations: list[str] = Field(default_factory=list)
    date_posted_max_days: int = 14
    min_fit_score: int = 6


class SearchEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    keywords: list[str]
    boards: list[VALID_BOARDS]


class SearchesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defaults: SearchDefaults = Field(default_factory=SearchDefaults)
    searches: list[SearchEntry] = Field(default_factory=list)


def load_searches(path: Path) -> SearchesConfig:
    if not path.is_file():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SearchesConfig.model_validate(data)
```

- [ ] **Step 7: Run, verify pass**

```bash
pytest tests/unit/test_searches.py -v
```

Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/searches.yaml.example bewerber/src/bewerber/discovery/ bewerber/tests/unit/test_searches.py .gitignore
git commit -m "feat(discovery): searches.yaml schema + loader with board validation"
```

---

## Task 5: BoardAdapter Protocol

**Files:**
- Create: `bewerber/src/bewerber/discovery/scrapers/__init__.py`
- Test: `bewerber/tests/unit/test_scraper_protocol.py`

A `Protocol` defining the scraper interface. No actual scraping in this task.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_scraper_protocol.py`:

```python
from datetime import date
from bewerber.discovery.scrapers import BoardAdapter, scraper_registry
from bewerber.shared.state_schema import RawJob


class FakeAdapter:
    name = "fake"

    def search(self, keywords, locations, max_age_days):
        return [
            RawJob(
                board="fake", external_id="1", url="https://x",
                title="t", company="c", location="l",
                posted_date=date(2026, 6, 1),
            )
        ]


def test_fake_adapter_satisfies_protocol():
    """A duck-typed class with .name and .search(...) IS-A BoardAdapter."""
    a: BoardAdapter = FakeAdapter()
    jobs = a.search(["k"], ["Leipzig"], max_age_days=14)
    assert jobs[0].board == "fake"


def test_scraper_registry_is_initially_empty():
    """Registry exists; modules will register themselves at import time."""
    # The registry is a dict[str, BoardAdapter]. It may be populated by the time
    # tests run if other scraper modules are imported elsewhere — we just check it exists.
    assert isinstance(scraper_registry, dict)
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_scraper_protocol.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/discovery/scrapers/__init__.py`**

```python
from typing import Protocol, runtime_checkable
from bewerber.shared.state_schema import RawJob


@runtime_checkable
class BoardAdapter(Protocol):
    """Each scraper module exposes one class/instance satisfying this protocol."""
    name: str

    def search(
        self,
        keywords: list[str],
        locations: list[str],
        max_age_days: int,
    ) -> list[RawJob]: ...


# Filled by individual scraper modules at import time (see arbeitsagentur.py etc.)
scraper_registry: dict[str, BoardAdapter] = {}
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_scraper_protocol.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/discovery/scrapers/ bewerber/tests/unit/test_scraper_protocol.py
git commit -m "feat(discovery): BoardAdapter protocol + scraper registry"
```

---

## Task 6: Arbeitsagentur Scraper (Official JSON API)

**Files:**
- Create: `bewerber/src/bewerber/discovery/scrapers/arbeitsagentur.py`
- Test: `bewerber/tests/unit/test_scraper_arbeitsagentur.py`
- Fixture: `bewerber/tests/fixtures/arbeitsagentur_response.json`

The Arbeitsagentur has a public job-search JSON API at `https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs`. Requires a `X-API-Key` header (free, register at the Arbeitsagentur developer portal — for tests we mock).

- [ ] **Step 1: Create a realistic API-response fixture**

Write to `bewerber/tests/fixtures/arbeitsagentur_response.json`:

```json
{
  "stellenangebote": [
    {
      "refnr": "10001-1003091744-S",
      "beruf": "KI-Manager/in",
      "titel": "Business AI Consultant (m/w/d) - KI Enablement & Kundenberatung",
      "arbeitgeber": "2b AHEAD ThinkTank GmbH",
      "arbeitsort": {
        "plz": "04179",
        "ort": "Leipzig",
        "region": "Sachsen",
        "land": "Deutschland"
      },
      "aktuelleVeroeffentlichungsdatum": "2026-05-19",
      "eintrittsdatum": "ab sofort",
      "externeUrl": null
    },
    {
      "refnr": "10001-9999999999-S",
      "beruf": "Senior KI-Berater/in",
      "titel": "Senior KI Consultant (m/w/d)",
      "arbeitgeber": "Acme GmbH",
      "arbeitsort": {
        "plz": "10115",
        "ort": "Berlin",
        "region": "Berlin",
        "land": "Deutschland"
      },
      "aktuelleVeroeffentlichungsdatum": "2026-06-10"
    }
  ],
  "maxErgebnisse": 2,
  "stellenangeboteCount": 2
}
```

- [ ] **Step 2: Write failing test**

Write to `bewerber/tests/unit/test_scraper_arbeitsagentur.py`:

```python
import json
from pathlib import Path
from datetime import date
from bewerber.discovery.scrapers.arbeitsagentur import (
    ArbeitsagenturAdapter, parse_arbeitsagentur_response, build_detail_url,
)


def test_parse_response_extracts_raw_jobs(fixtures_dir: Path):
    data = json.loads((fixtures_dir / "arbeitsagentur_response.json").read_text())
    jobs = parse_arbeitsagentur_response(data)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.board == "arbeitsagentur"
    assert j.external_id == "10001-1003091744-S"
    assert "Business AI Consultant" in j.title
    assert j.company == "2b AHEAD ThinkTank GmbH"
    assert j.location == "Leipzig"
    assert j.posted_date == date(2026, 5, 19)
    assert j.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003091744-S"


def test_build_detail_url():
    assert build_detail_url("10001-1003091744-S") == (
        "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003091744-S"
    )


def test_adapter_calls_api_and_parses(mocker, fixtures_dir: Path):
    fixture_data = json.loads((fixtures_dir / "arbeitsagentur_response.json").read_text())
    fake_resp = mocker.Mock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = fixture_data
    fake_resp.raise_for_status = mocker.Mock()
    mocker.patch(
        "bewerber.discovery.scrapers.arbeitsagentur.requests.get",
        return_value=fake_resp,
    )

    adapter = ArbeitsagenturAdapter(api_key="test-key")
    jobs = adapter.search(keywords=["KI Manager"], locations=["Leipzig"], max_age_days=30)
    assert len(jobs) == 2

    import bewerber.discovery.scrapers.arbeitsagentur as mod
    args, kwargs = mod.requests.get.call_args
    assert "X-API-Key" in kwargs["headers"]
    assert kwargs["headers"]["X-API-Key"] == "test-key"
    assert "was=KI" in kwargs["url"] or kwargs["params"]["was"] == "KI Manager"


def test_adapter_registers_in_scraper_registry():
    from bewerber.discovery.scrapers import scraper_registry
    from bewerber.discovery.scrapers.arbeitsagentur import ArbeitsagenturAdapter  # import triggers registration
    assert "arbeitsagentur" in scraper_registry
    assert isinstance(scraper_registry["arbeitsagentur"], ArbeitsagenturAdapter)
```

- [ ] **Step 3: Run, verify fail**

```bash
pytest tests/unit/test_scraper_arbeitsagentur.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `bewerber/src/bewerber/discovery/scrapers/arbeitsagentur.py`**

```python
import os
from datetime import date, timedelta
from typing import Optional
import requests

from bewerber.shared.state_schema import RawJob
from bewerber.discovery.scrapers import scraper_registry


API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
DETAIL_URL_BASE = "https://www.arbeitsagentur.de/jobsuche/jobdetail"


def build_detail_url(refnr: str) -> str:
    return f"{DETAIL_URL_BASE}/{refnr}"


def parse_arbeitsagentur_response(data: dict) -> list[RawJob]:
    """Map the Arbeitsagentur v4 JSON response to RawJob list."""
    result: list[RawJob] = []
    for entry in data.get("stellenangebote", []):
        refnr = entry.get("refnr")
        if not refnr:
            continue
        ort = (entry.get("arbeitsort") or {}).get("ort") or ""
        published = entry.get("aktuelleVeroeffentlichungsdatum")
        posted: Optional[date] = None
        if published:
            try:
                posted = date.fromisoformat(published)
            except ValueError:
                posted = None
        result.append(RawJob(
            board="arbeitsagentur",
            external_id=refnr,
            url=build_detail_url(refnr),
            title=entry.get("titel") or entry.get("beruf") or "",
            company=entry.get("arbeitgeber") or "",
            location=ort,
            posted_date=posted,
        ))
    return result


class ArbeitsagenturAdapter:
    name = "arbeitsagentur"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("ARBEITSAGENTUR_API_KEY", "")

    def search(
        self,
        keywords: list[str],
        locations: list[str],
        max_age_days: int,
    ) -> list[RawJob]:
        if not self.api_key:
            raise RuntimeError(
                "ARBEITSAGENTUR_API_KEY not set. "
                "Register at https://jobsuche.api.bund.dev and put the key in .env."
            )
        # Combine keywords with OR; multiple location lookups happen by repeating the request per location.
        was = " OR ".join(keywords) if keywords else ""
        results: list[RawJob] = []
        cutoff = date.today() - timedelta(days=max_age_days)
        for loc in locations or [""]:
            params = {"was": was, "wo": loc, "size": 50, "angebotsart": 1}
            resp = requests.get(
                url=API_BASE,
                headers={"X-API-Key": self.api_key, "User-Agent": "bewerber/0.1"},
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            for job in parse_arbeitsagentur_response(resp.json()):
                if job.posted_date and job.posted_date < cutoff:
                    continue
                results.append(job)
        return results


# Register a default instance (api_key picked up from env at first use).
scraper_registry["arbeitsagentur"] = ArbeitsagenturAdapter()
```

- [ ] **Step 5: Run, verify pass**

```bash
pytest tests/unit/test_scraper_arbeitsagentur.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/discovery/scrapers/arbeitsagentur.py bewerber/tests/unit/test_scraper_arbeitsagentur.py bewerber/tests/fixtures/arbeitsagentur_response.json
git commit -m "feat(discovery): Arbeitsagentur scraper via official JSON v4 API"
```

---

## Task 7: LinkedIn Scraper (via python-jobspy)

**Files:**
- Create: `bewerber/src/bewerber/discovery/scrapers/linkedin.py`
- Test: `bewerber/tests/unit/test_scraper_linkedin.py`

We delegate the scraping to `python-jobspy` and adapt its DataFrame output to `RawJob`.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_scraper_linkedin.py`:

```python
from datetime import date
from bewerber.discovery.scrapers.linkedin import (
    LinkedInAdapter, jobspy_row_to_raw_job,
)


def _fake_dataframe(rows):
    """Build a mock pandas-like object yielding `rows` from .iterrows()."""
    class _DF:
        def iterrows(self):
            return iter([(i, r) for i, r in enumerate(rows)])
        def __len__(self):
            return len(rows)
    return _DF()


def test_jobspy_row_to_raw_job():
    row = {
        "site": "linkedin",
        "id": "li-12345",
        "job_url": "https://www.linkedin.com/jobs/view/12345",
        "title": "AI Product Manager",
        "company": "Acme",
        "location": "Berlin",
        "date_posted": "2026-06-05",
        "description": "Spannende Rolle ...",
    }
    job = jobspy_row_to_raw_job(row)
    assert job.board == "linkedin"
    assert job.external_id == "li-12345"
    assert job.url.endswith("/12345")
    assert job.title == "AI Product Manager"
    assert job.posted_date == date(2026, 6, 5)
    assert job.description.startswith("Spannende")


def test_jobspy_row_missing_id_falls_back_to_url_hash():
    row = {
        "site": "linkedin",
        "job_url": "https://linkedin.com/jobs/view/99999",
        "title": "x", "company": "c", "location": "l", "id": None,
        "date_posted": None, "description": None,
    }
    job = jobspy_row_to_raw_job(row)
    assert job.external_id  # non-empty derived from URL


def test_adapter_calls_jobspy_with_linkedin_only(mocker):
    rows = [{
        "site": "linkedin", "id": "1", "job_url": "https://x", "title": "t",
        "company": "c", "location": "l", "date_posted": None, "description": None,
    }]
    fake_scrape = mocker.patch(
        "bewerber.discovery.scrapers.linkedin.scrape_jobs",
        return_value=_fake_dataframe(rows),
    )
    adapter = LinkedInAdapter()
    jobs = adapter.search(keywords=["KI Manager"], locations=["Leipzig"], max_age_days=14)
    assert len(jobs) == 1
    args, kwargs = fake_scrape.call_args
    assert kwargs["site_name"] == ["linkedin"]
    assert kwargs["search_term"] == "KI Manager"
    assert kwargs["location"] == "Leipzig"
    assert kwargs["hours_old"] == 14 * 24  # max_age_days → hours


def test_adapter_registers_in_scraper_registry():
    from bewerber.discovery.scrapers import scraper_registry
    from bewerber.discovery.scrapers.linkedin import LinkedInAdapter  # noqa: F401  triggers registration
    assert "linkedin" in scraper_registry
    assert isinstance(scraper_registry["linkedin"], LinkedInAdapter)
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_scraper_linkedin.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/discovery/scrapers/linkedin.py`**

```python
import hashlib
from datetime import date
from typing import Optional
from jobspy import scrape_jobs

from bewerber.shared.state_schema import RawJob
from bewerber.discovery.scrapers import scraper_registry


def jobspy_row_to_raw_job(row: dict) -> RawJob:
    """Map a single jobspy DataFrame row (LinkedIn) to RawJob."""
    ext = row.get("id")
    url = row.get("job_url") or ""
    if not ext:
        ext = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    posted_raw = row.get("date_posted")
    posted: Optional[date] = None
    if posted_raw:
        try:
            posted = date.fromisoformat(str(posted_raw))
        except ValueError:
            posted = None
    description = row.get("description") or None
    return RawJob(
        board="linkedin",
        external_id=str(ext),
        url=url,
        title=row.get("title") or "",
        company=row.get("company") or "",
        location=row.get("location") or "",
        posted_date=posted,
        description=description,
    )


class LinkedInAdapter:
    name = "linkedin"

    def search(
        self,
        keywords: list[str],
        locations: list[str],
        max_age_days: int,
    ) -> list[RawJob]:
        results: list[RawJob] = []
        for kw in keywords or [""]:
            for loc in locations or [""]:
                df = scrape_jobs(
                    site_name=["linkedin"],
                    search_term=kw,
                    location=loc,
                    hours_old=max_age_days * 24,
                    results_wanted=30,
                    country_indeed="Germany",
                )
                for _, row in df.iterrows():
                    results.append(jobspy_row_to_raw_job(row))
        return results


scraper_registry["linkedin"] = LinkedInAdapter()
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_scraper_linkedin.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/discovery/scrapers/linkedin.py bewerber/tests/unit/test_scraper_linkedin.py
git commit -m "feat(discovery): LinkedIn scraper via python-jobspy"
```

---

## Task 8: Indeed Scraper (via python-jobspy)

**Files:**
- Create: `bewerber/src/bewerber/discovery/scrapers/indeed.py`
- Test: `bewerber/tests/unit/test_scraper_indeed.py`

Symmetrical to LinkedIn, but with `site_name=["indeed"]` and `country_indeed="Germany"`.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_scraper_indeed.py`:

```python
from bewerber.discovery.scrapers.indeed import IndeedAdapter, jobspy_row_to_raw_job_indeed


def _fake_dataframe(rows):
    class _DF:
        def iterrows(self):
            return iter([(i, r) for i, r in enumerate(rows)])
        def __len__(self):
            return len(rows)
    return _DF()


def test_jobspy_row_to_raw_job_indeed_sets_board():
    row = {
        "site": "indeed", "id": "id-42", "job_url": "https://de.indeed.com/job/42",
        "title": "t", "company": "c", "location": "l",
        "date_posted": None, "description": None,
    }
    job = jobspy_row_to_raw_job_indeed(row)
    assert job.board == "indeed"
    assert job.external_id == "id-42"


def test_adapter_calls_jobspy_with_indeed_only(mocker):
    rows = [{
        "site": "indeed", "id": "1", "job_url": "https://x", "title": "t",
        "company": "c", "location": "l", "date_posted": None, "description": None,
    }]
    fake = mocker.patch(
        "bewerber.discovery.scrapers.indeed.scrape_jobs",
        return_value=_fake_dataframe(rows),
    )
    adapter = IndeedAdapter()
    jobs = adapter.search(keywords=["KI Manager"], locations=["Leipzig"], max_age_days=14)
    assert len(jobs) == 1
    kwargs = fake.call_args.kwargs
    assert kwargs["site_name"] == ["indeed"]
    assert kwargs["country_indeed"] == "Germany"


def test_adapter_registers_in_scraper_registry():
    from bewerber.discovery.scrapers import scraper_registry
    from bewerber.discovery.scrapers.indeed import IndeedAdapter  # noqa
    assert "indeed" in scraper_registry
    assert isinstance(scraper_registry["indeed"], IndeedAdapter)
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_scraper_indeed.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/discovery/scrapers/indeed.py`**

```python
import hashlib
from datetime import date
from typing import Optional
from jobspy import scrape_jobs

from bewerber.shared.state_schema import RawJob
from bewerber.discovery.scrapers import scraper_registry


def jobspy_row_to_raw_job_indeed(row: dict) -> RawJob:
    ext = row.get("id")
    url = row.get("job_url") or ""
    if not ext:
        ext = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    posted_raw = row.get("date_posted")
    posted: Optional[date] = None
    if posted_raw:
        try:
            posted = date.fromisoformat(str(posted_raw))
        except ValueError:
            posted = None
    return RawJob(
        board="indeed",
        external_id=str(ext),
        url=url,
        title=row.get("title") or "",
        company=row.get("company") or "",
        location=row.get("location") or "",
        posted_date=posted,
        description=row.get("description") or None,
    )


class IndeedAdapter:
    name = "indeed"

    def search(
        self,
        keywords: list[str],
        locations: list[str],
        max_age_days: int,
    ) -> list[RawJob]:
        results: list[RawJob] = []
        for kw in keywords or [""]:
            for loc in locations or [""]:
                df = scrape_jobs(
                    site_name=["indeed"],
                    search_term=kw,
                    location=loc,
                    hours_old=max_age_days * 24,
                    results_wanted=30,
                    country_indeed="Germany",
                )
                for _, row in df.iterrows():
                    results.append(jobspy_row_to_raw_job_indeed(row))
        return results


scraper_registry["indeed"] = IndeedAdapter()
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_scraper_indeed.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/discovery/scrapers/indeed.py bewerber/tests/unit/test_scraper_indeed.py
git commit -m "feat(discovery): Indeed scraper via python-jobspy (Germany)"
```

---

## Task 9: Enrich (Fetch Full Posting Description)

**Files:**
- Create: `bewerber/src/bewerber/discovery/enrich.py`
- Test: `bewerber/tests/unit/test_enrich.py`
- Fixture: `bewerber/tests/fixtures/posting_with_full_description.html`

If a scraper returns a job without description (typically Arbeitsagentur), we fetch the detail URL and extract the main text via `readability-lxml`.

- [ ] **Step 1: Create fixture**

Write to `bewerber/tests/fixtures/posting_with_full_description.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Stellenausschreibung</title></head>
<body>
  <nav>navigation links blah</nav>
  <header>header noise</header>
  <main>
    <h1>Business AI Consultant</h1>
    <p>Wir suchen einen erfahrenen Berater, der unsere Kunden bei der Identifikation
       und Umsetzung von KI-Use-Cases unterstützt.</p>
    <h2>Anforderungen</h2>
    <ul>
      <li>Erfahrung mit n8n, Python, OpenAI</li>
      <li>Kommunikationsstärke</li>
    </ul>
  </main>
  <footer>footer noise about cookies</footer>
</body>
</html>
```

- [ ] **Step 2: Write failing test**

Write to `bewerber/tests/unit/test_enrich.py`:

```python
import hashlib
from pathlib import Path
from bewerber.discovery.enrich import (
    enrich_job, extract_main_text, _hash_description,
)
from bewerber.shared.state_schema import RawJob


def _raw(description=None) -> RawJob:
    return RawJob(
        board="arbeitsagentur",
        external_id="x1",
        url="https://example.com/job/1",
        title="t", company="c", location="l",
        description=description,
    )


def test_extract_main_text_finds_main_content(fixtures_dir: Path):
    html = (fixtures_dir / "posting_with_full_description.html").read_text(encoding="utf-8")
    text = extract_main_text(html)
    assert "Business AI Consultant" in text
    assert "n8n" in text
    assert "footer noise" not in text  # readability strips boilerplate


def test_enrich_keeps_existing_description(mocker):
    job = _raw(description="bereits da")
    fake_get = mocker.patch("bewerber.discovery.enrich.requests.get")
    result = enrich_job(job)
    assert result.description == "bereits da"
    fake_get.assert_not_called()


def test_enrich_fetches_and_sets_description_when_missing(mocker, fixtures_dir: Path):
    html = (fixtures_dir / "posting_with_full_description.html").read_text(encoding="utf-8")
    fake_resp = mocker.Mock()
    fake_resp.text = html
    fake_resp.raise_for_status = mocker.Mock()
    fake_resp.status_code = 200
    mocker.patch("bewerber.discovery.enrich.requests.get", return_value=fake_resp)

    job = _raw(description=None)
    result = enrich_job(job)
    assert "Business AI Consultant" in (result.description or "")
    assert result.description_hash is not None
    assert result.description_hash == _hash_description(result.description)


def test_enrich_swallows_http_failure_and_returns_job_unchanged(mocker):
    job = _raw(description=None)
    mocker.patch(
        "bewerber.discovery.enrich.requests.get",
        side_effect=__import__("requests").RequestException("network"),
    )
    result = enrich_job(job)
    assert result.description is None  # not raised, just left empty
```

- [ ] **Step 3: Run, verify fail**

```bash
pytest tests/unit/test_enrich.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `bewerber/src/bewerber/discovery/enrich.py`**

```python
import hashlib
import requests
from readability import Document
from typing import Optional
import re

from bewerber.shared.state_schema import RawJob


def _hash_description(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def extract_main_text(html: str) -> str:
    """Use readability to isolate main content, then strip remaining tags."""
    summary_html = Document(html).summary()
    # Strip tags + collapse whitespace
    text = re.sub(r"<[^>]+>", " ", summary_html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def enrich_job(job: RawJob, timeout: int = 20) -> RawJob:
    """Fetch the posting URL and populate description if not already present.

    On network failure: leave description as-is and return the job unchanged.
    """
    if job.description:
        return job

    try:
        resp = requests.get(
            job.url,
            headers={"User-Agent": "bewerber/0.1 (+https://github.com/)"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return job

    text = extract_main_text(resp.text)
    if not text:
        return job
    return job.model_copy(update={
        "description": text,
        "description_hash": _hash_description(text),
    })
```

- [ ] **Step 5: Run, verify pass**

```bash
pytest tests/unit/test_enrich.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/discovery/enrich.py bewerber/tests/unit/test_enrich.py bewerber/tests/fixtures/posting_with_full_description.html
git commit -m "feat(discovery): enrich job via requests + readability-lxml when description missing"
```

---

## Task 10: LLM Scoring

**Files:**
- Create: `bewerber/src/bewerber/discovery/scoring.py`
- Test: `bewerber/tests/unit/test_scoring.py`

LLM pass: given a RawJob (with description) + master_profile.yaml → returns a `Scoring`.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_scoring.py`:

```python
from bewerber.discovery.scoring import score_job
from bewerber.shared.state_schema import RawJob, Scoring


def _job(description="Beschreibung zur Stelle.") -> RawJob:
    return RawJob(
        board="arbeitsagentur", external_id="1",
        url="https://x", title="KI Manager", company="BMW",
        location="München", description=description,
    )


def test_score_job_returns_scoring_from_llm(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = Scoring(
        fit_score=8,
        begruendung="Profil passt zu KI/Workflow-Schwerpunkt.",
        matched_skills=["n8n", "Python"],
        missing_skills=["SAP"],
        red_flags=[],
        verbessern_in_anschreiben=["SAP-Erfahrung framen"],
    )
    result = score_job(
        job=_job(),
        master_yaml_text="person:\n  name: Steve",
        llm=fake_llm,
    )
    assert isinstance(result, Scoring)
    assert result.fit_score == 8
    assert "n8n" in result.matched_skills

    args, kwargs = fake_llm.structured.call_args
    user_prompt = kwargs["user"]
    assert "KI Manager" in user_prompt
    assert "BMW" in user_prompt
    assert "Beschreibung zur Stelle" in user_prompt
    assert "Steve" in user_prompt  # master profile in prompt
    assert kwargs["schema"] is Scoring


def test_score_job_uses_title_company_when_description_missing(mocker):
    """Even without description, scoring still works on title+company."""
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = Scoring(
        fit_score=5, begruendung="x", matched_skills=[],
        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
    )
    job = _job(description=None)
    score_job(job=job, master_yaml_text="x", llm=fake_llm)
    user_prompt = fake_llm.structured.call_args.kwargs["user"]
    assert "KI Manager" in user_prompt
    assert "(keine ausführliche Beschreibung verfügbar)" in user_prompt
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_scoring.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/discovery/scoring.py`**

```python
from bewerber.shared.llm import LLMClient
from bewerber.shared.state_schema import RawJob, Scoring


SCORING_SYSTEM_PROMPT = """Du bist ein kritischer deutscher Karriere-Coach.
Du bewertest, wie gut eine Stellenausschreibung zum Bewerber-Profil passt.

REGELN:
1. Antworte ausschließlich auf Deutsch.
2. fit_score: 1 (kein Match) bis 10 (perfekter Match). Sei realistisch, nicht hoffnungsfroh.
3. Erfinde keine Skills, die nicht im Master-Profil stehen.
4. begruendung: 2-3 prägnante Sätze. Was passt, was passt nicht.
5. matched_skills: Skills aus dem Master, die im Posting gefordert werden.
6. missing_skills: Skills, die im Posting gefordert werden, aber nicht im Master stehen.
7. red_flags: Punkte, die gegen die Stelle sprechen (Vor-Ort-Zwang, Branche-Mismatch, etc.).
8. verbessern_in_anschreiben: Konkrete Aspekte, die im Anschreiben adressiert werden sollten.
9. Verwende AUSSCHLIESSLICH klassische Bindestriche (-). KEINE em-/en-dashes.
"""


def score_job(job: RawJob, master_yaml_text: str, llm: LLMClient) -> Scoring:
    description = job.description or "(keine ausführliche Beschreibung verfügbar)"
    user = (
        "BEWERBER-PROFIL:\n"
        f"{master_yaml_text}\n\n"
        "STELLENAUSSCHREIBUNG:\n"
        f"Titel: {job.title}\n"
        f"Firma: {job.company}\n"
        f"Ort:   {job.location}\n"
        f"URL:   {job.url}\n\n"
        f"Beschreibung:\n{description}\n\n"
        "Bewerte das Match."
    )
    return llm.structured(
        system=SCORING_SYSTEM_PROMPT,
        user=user,
        schema=Scoring,
    )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_scoring.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/discovery/scoring.py bewerber/tests/unit/test_scoring.py
git commit -m "feat(discovery): LLM scoring against master_profile (fit_score 1-10 + reasoning)"
```

---

## Task 11: Discovery Orchestrator

**Files:**
- Create: `bewerber/src/bewerber/discovery/orchestrator.py`
- Test: `bewerber/tests/unit/test_discovery_orchestrator.py`

Composes: load searches → for each search → for each board → scrape → enrich → score → upsert into state. Isolates per-board errors.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_discovery_orchestrator.py`:

```python
from datetime import date
from bewerber.discovery.orchestrator import discover
from bewerber.discovery.searches import SearchesConfig, SearchEntry, SearchDefaults
from bewerber.shared.state_schema import (
    BewerberState, RawJob, Scoring, JobStatus,
)


def _job(board="arbeitsagentur", ext="1", desc="Beschreibung") -> RawJob:
    return RawJob(
        board=board, external_id=ext,
        url=f"https://{board}/{ext}",
        title="KI Manager", company="Acme", location="Leipzig",
        description=desc,
    )


def test_discover_runs_each_board_per_search_and_upserts(tmp_path, mocker, monkeypatch):
    """Two searches × two boards → 4 scraper calls; each result scored and stored."""
    fake_adapter_a = mocker.Mock()
    fake_adapter_a.name = "arbeitsagentur"
    fake_adapter_a.search.return_value = [_job("arbeitsagentur", "1")]
    fake_adapter_b = mocker.Mock()
    fake_adapter_b.name = "linkedin"
    fake_adapter_b.search.return_value = [_job("linkedin", "li-2")]

    fake_registry = {"arbeitsagentur": fake_adapter_a, "linkedin": fake_adapter_b}
    monkeypatch.setattr("bewerber.discovery.orchestrator.scraper_registry", fake_registry)

    fake_enrich = mocker.patch(
        "bewerber.discovery.orchestrator.enrich_job",
        side_effect=lambda j: j,
    )
    fake_score = mocker.patch(
        "bewerber.discovery.orchestrator.score_job",
        return_value=Scoring(
            fit_score=7, begruendung="ok", matched_skills=[],
            missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
        ),
    )

    config = SearchesConfig(
        defaults=SearchDefaults(locations=["Leipzig"], date_posted_max_days=14),
        searches=[
            SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur", "linkedin"]),
            SearchEntry(name="B", keywords=["Manager"], boards=["arbeitsagentur"]),
        ],
    )

    state = BewerberState()
    fake_llm = mocker.Mock()
    discover(config, state=state, master_yaml_text="master", llm=fake_llm)

    # 3 scraper invocations: search-A × 2 boards + search-B × 1 board
    assert fake_adapter_a.search.call_count + fake_adapter_b.search.call_count == 3
    # Enrich + score called for each unique RawJob
    assert fake_enrich.call_count == 3
    assert fake_score.call_count == 3
    # Both jobs in state
    assert "arbeitsagentur-1" in state.jobs
    assert "linkedin-li-2" in state.jobs
    # Scoring attached
    assert state.jobs["arbeitsagentur-1"].scoring.fit_score == 7


def test_discover_isolates_board_failures(tmp_path, mocker, monkeypatch):
    """If one scraper raises, others still run, and an error is recorded in state."""
    ok = mocker.Mock()
    ok.name = "arbeitsagentur"
    ok.search.return_value = [_job("arbeitsagentur", "1")]
    broken = mocker.Mock()
    broken.name = "linkedin"
    broken.search.side_effect = RuntimeError("rate-limited")

    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": ok, "linkedin": broken},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=7, begruendung="x", matched_skills=[], missing_skills=[],
        red_flags=[], verbessern_in_anschreiben=[],
    ))

    config = SearchesConfig(searches=[
        SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur", "linkedin"]),
    ])
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    assert "arbeitsagentur-1" in state.jobs  # ok scraper succeeded
    assert "linkedin" in state.scrape_errors
    assert "rate-limited" in state.scrape_errors["linkedin"].last_error


def test_discover_skips_rescoring_when_description_hash_unchanged(mocker, monkeypatch):
    """If a job comes back from scrape with same description_hash, do not re-score."""
    pre_existing = _job("arbeitsagentur", "1", desc="A")
    pre_existing = pre_existing.model_copy(update={"description_hash": "h-A"})
    state = BewerberState()
    from bewerber.shared.state_schema import TrackedJob
    state.jobs["arbeitsagentur-1"] = TrackedJob(
        raw=pre_existing,
        scoring=Scoring(
            fit_score=9, begruendung="alt", matched_skills=[],
            missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
        ),
        status=JobStatus.APPLIED,
    )

    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [pre_existing]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    rescore = mocker.patch("bewerber.discovery.orchestrator.score_job")

    config = SearchesConfig(searches=[
        SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur"]),
    ])
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    rescore.assert_not_called()  # description unchanged → no re-scoring
    # Existing scoring + status preserved
    assert state.jobs["arbeitsagentur-1"].scoring.fit_score == 9
    assert state.jobs["arbeitsagentur-1"].status == JobStatus.APPLIED
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_discovery_orchestrator.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/discovery/orchestrator.py`**

```python
from datetime import datetime
from typing import Optional

from bewerber.shared.llm import LLMClient
from bewerber.shared.state import upsert_job
from bewerber.shared.state_schema import (
    BewerberState, RawJob, Scoring, ScrapeError, TrackedJob,
)
from bewerber.discovery.scrapers import scraper_registry
from bewerber.discovery.searches import SearchesConfig
from bewerber.discovery.enrich import enrich_job
from bewerber.discovery.scoring import score_job


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def discover(
    config: SearchesConfig,
    *,
    state: BewerberState,
    master_yaml_text: str,
    llm: LLMClient,
) -> BewerberState:
    """Run scrape → enrich → score → upsert for each search × board.

    Per-board errors are caught and recorded in state.scrape_errors;
    other boards continue running.
    """
    state.last_discovery_run = _now_iso()

    for search in config.searches:
        for board in search.boards:
            adapter = scraper_registry.get(board)
            if adapter is None:
                state.scrape_errors[board] = ScrapeError(
                    last_error=f"No adapter registered for board {board!r}",
                    at=_now_iso(),
                )
                continue
            try:
                raw_jobs = adapter.search(
                    keywords=search.keywords,
                    locations=config.defaults.locations,
                    max_age_days=config.defaults.date_posted_max_days,
                )
            except Exception as e:  # noqa: BLE001 - isolation is the whole point
                state.scrape_errors[board] = ScrapeError(
                    last_error=str(e),
                    at=_now_iso(),
                )
                continue
            # Clear prior error for this board on success
            state.scrape_errors.pop(board, None)

            for raw in raw_jobs:
                _process_one(raw, state=state, master_yaml_text=master_yaml_text, llm=llm)
    return state


def _process_one(
    raw: RawJob,
    *,
    state: BewerberState,
    master_yaml_text: str,
    llm: LLMClient,
) -> None:
    enriched = enrich_job(raw)
    job_id = f"{enriched.board}-{enriched.external_id}"
    existing = state.jobs.get(job_id)

    if (
        existing is not None
        and existing.scoring is not None
        and enriched.description_hash is not None
        and enriched.description_hash == existing.raw.description_hash
    ):
        # No content change → keep existing scoring; just upsert (raw may have fresher fields)
        tracked = TrackedJob(raw=enriched, scoring=existing.scoring)
    else:
        scoring = score_job(job=enriched, master_yaml_text=master_yaml_text, llm=llm)
        tracked = TrackedJob(
            raw=enriched,
            scoring=scoring,
            first_seen=_now_iso() if existing is None else existing.first_seen,
        )

    upsert_job(state, tracked)
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_discovery_orchestrator.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/discovery/orchestrator.py bewerber/tests/unit/test_discovery_orchestrator.py
git commit -m "feat(discovery): orchestrator with per-board error isolation + smart re-scoring"
```

---

## Task 12: `bewerber discover` CLI Command

**Files:**
- Modify: `bewerber/src/bewerber/cli.py`
- Test: `bewerber/tests/unit/test_cli_b.py`

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_cli_b.py`:

```python
import yaml
from pathlib import Path
from click.testing import CliRunner
from bewerber.cli import main


def _write_master_and_searches(workspace: Path, documents: Path) -> None:
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True, exist_ok=True)
    (bewerber_dir / "master_profile.yaml").write_text(yaml.safe_dump({
        "person": {"name": "Steve", "email": "s@x.de"},
        "berufsprofil": "kurz",
        "zielposition": [],
    }, allow_unicode=True))
    (bewerber_dir / "searches.yaml").write_text(yaml.safe_dump({
        "defaults": {"locations": ["Leipzig"], "date_posted_max_days": 14, "min_fit_score": 6},
        "searches": [{"name": "KI", "keywords": ["KI Manager"], "boards": ["arbeitsagentur"]}],
    }, allow_unicode=True))
    (documents / "Bewerbungsunterlagen" / "Bewerbungen").mkdir(parents=True)


def test_discover_loads_config_and_calls_orchestrator(tmp_path, monkeypatch, mocker):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    _write_master_and_searches(workspace, tmp_path)

    fake_discover = mocker.patch("bewerber.cli.discover")
    mocker.patch("bewerber.cli.LLMClient")

    runner = CliRunner()
    result = runner.invoke(main, ["discover"])
    assert result.exit_code == 0, result.output
    fake_discover.assert_called_once()
    # Output mentions the count of searches
    assert "1 Suche" in result.output or "1 search" in result.output.lower() or "Sucheinträge" in result.output


def test_discover_fails_if_searches_yaml_missing(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    (workspace / "bewerber").mkdir(parents=True)
    (workspace / "bewerber" / "master_profile.yaml").write_text("person: {name: x, email: x@y.de}\nberufsprofil: x\nzielposition: []")
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))

    runner = CliRunner()
    result = runner.invoke(main, ["discover"])
    assert result.exit_code != 0
    assert "searches.yaml" in result.output


def test_discover_fails_if_master_profile_missing(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    (workspace / "bewerber").mkdir(parents=True)
    (workspace / "bewerber" / "searches.yaml").write_text("defaults: {}\nsearches: []")
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))

    runner = CliRunner()
    result = runner.invoke(main, ["discover"])
    assert result.exit_code != 0
    assert "master_profile.yaml" in result.output
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_cli_b.py -v
```

Expected: AttributeError / failure: the `discover` command doesn't exist yet.

- [ ] **Step 3: Update `bewerber/src/bewerber/cli.py`**

Add imports near the existing `from bewerber.tailoring.*` block:

```python
from bewerber.discovery.searches import load_searches
from bewerber.discovery.orchestrator import discover
from bewerber.shared.state import load_state, save_state
```

Append a new top-level command (after `cmd_tailor`, before `if __name__ == "__main__":`):

```python
@main.command("discover")
def cmd_discover() -> None:
    """Sucht Jobs auf den konfigurierten Boards, scort sie gegen master_profile, schreibt state.json."""
    paths = Paths()
    if not paths.master_profile.is_file():
        click.echo(f"Fehler: {paths.master_profile} fehlt. Erst `bewerber profile init` ausführen.")
        raise click.exceptions.Exit(1)
    searches_path = paths.bewerber_dir / "searches.yaml"
    if not searches_path.is_file():
        click.echo(
            f"Fehler: {searches_path} fehlt. "
            f"Kopiere `bewerber/searches.yaml.example` zu `bewerber/searches.yaml` und passe sie an."
        )
        raise click.exceptions.Exit(1)

    config = load_searches(searches_path)
    if not config.searches:
        click.echo("Keine Sucheinträge in searches.yaml definiert. Nichts zu tun.")
        return

    click.echo(f"Lade {len(config.searches)} Sucheinträge …")
    master_yaml_text = paths.master_profile.read_text(encoding="utf-8")
    state = load_state(paths.state_json)
    llm = LLMClient()
    discover(config, state=state, master_yaml_text=master_yaml_text, llm=llm)
    save_state(paths.state_json, state)

    fit_jobs = [j for j in state.jobs.values() if j.scoring and j.scoring.fit_score >= config.defaults.min_fit_score]
    click.echo(f"✔ {len(state.jobs)} Jobs insgesamt, {len(fit_jobs)} davon mit Fit-Score >= {config.defaults.min_fit_score}")
    if state.scrape_errors:
        click.echo("Scrape-Fehler:")
        for board, err in state.scrape_errors.items():
            click.echo(f"  · {board}: {err.last_error}")
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_cli_b.py::test_discover_loads_config_and_calls_orchestrator -v
pytest tests/unit/test_cli_b.py::test_discover_fails_if_searches_yaml_missing -v
pytest tests/unit/test_cli_b.py::test_discover_fails_if_master_profile_missing -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/cli.py bewerber/tests/unit/test_cli_b.py
git commit -m "feat(cli): wire bewerber discover command (scrape + enrich + score + save)"
```

---

## Task 13: Status Mutation CLI (`mark`, `note`)

**Files:**
- Modify: `bewerber/src/bewerber/cli.py`
- Modify: `bewerber/tests/unit/test_cli_b.py` (append)

CLI commands to update a tracked job's status and notes.

- [ ] **Step 1: Append failing tests** to `bewerber/tests/unit/test_cli_b.py`:

```python
from bewerber.shared.state import save_state, load_state
from bewerber.shared.state_schema import BewerberState, RawJob, TrackedJob, JobStatus


def _seed_state(workspace: Path) -> Path:
    bd = workspace / "bewerber"
    bd.mkdir(parents=True, exist_ok=True)
    job = TrackedJob(raw=RawJob(
        board="arbeitsagentur", external_id="x1",
        url="https://x", title="t", company="c", location="l",
    ))
    state = BewerberState(jobs={"arbeitsagentur-x1": job})
    state_path = bd / "state.json"
    save_state(state_path, state)
    return state_path


def test_mark_updates_status_and_appends_history(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    state_path = _seed_state(workspace)

    runner = CliRunner()
    result = runner.invoke(main, ["mark", "arbeitsagentur-x1", "applied", "--link", "https://applied.example"])
    assert result.exit_code == 0, result.output

    state = load_state(state_path)
    job = state.jobs["arbeitsagentur-x1"]
    assert job.status == JobStatus.APPLIED
    assert job.application_link == "https://applied.example"
    assert len(job.status_history) == 1
    assert job.status_history[0].status == JobStatus.APPLIED


def test_mark_invalid_status_rejected(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    _seed_state(workspace)
    runner = CliRunner()
    result = runner.invoke(main, ["mark", "arbeitsagentur-x1", "applied-yesterday"])
    assert result.exit_code != 0


def test_mark_unknown_job_id(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    _seed_state(workspace)
    runner = CliRunner()
    result = runner.invoke(main, ["mark", "nonexistent-9999", "applied"])
    assert result.exit_code != 0
    assert "nicht gefunden" in result.output.lower() or "unknown" in result.output.lower()


def test_note_appends_to_notes_field(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    state_path = _seed_state(workspace)

    runner = CliRunner()
    r1 = runner.invoke(main, ["note", "arbeitsagentur-x1", "Telefoniert am 13.06."])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(main, ["note", "arbeitsagentur-x1", "Interview-Einladung erhalten."])
    assert r2.exit_code == 0

    state = load_state(state_path)
    notes = state.jobs["arbeitsagentur-x1"].notes
    assert "Telefoniert" in notes
    assert "Interview-Einladung" in notes
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_cli_b.py -v
```

Expected: 4 new tests fail (commands not defined).

- [ ] **Step 3: Update `bewerber/src/bewerber/cli.py`**

Add to the existing imports near `from bewerber.shared.state ...`:

```python
from datetime import datetime as _datetime
from bewerber.shared.state_schema import JobStatus, StatusHistoryEntry
```

Append two top-level commands:

```python
def _parse_status(value: str) -> JobStatus:
    try:
        return JobStatus(value)
    except ValueError:
        valid = ", ".join(s.value for s in JobStatus)
        raise click.BadParameter(f"Ungültiger Status {value!r}. Erlaubt: {valid}")


@main.command("mark")
@click.argument("job_id")
@click.argument("status", callback=lambda ctx, param, val: _parse_status(val))
@click.option("--link", "application_link", help="URL der eingereichten Bewerbung (für Status `applied`).")
@click.option("--at", "interview_at", help="Datum/Zeit eines Interviews (ISO oder freie Form).")
def cmd_mark(job_id: str, status: JobStatus, application_link: str | None, interview_at: str | None) -> None:
    """Setzt den Status einer Bewerbung (discovered/shortlisted/tailored/applied/interview/offer/rejected/withdrawn)."""
    paths = Paths()
    state = load_state(paths.state_json)
    if job_id not in state.jobs:
        click.echo(f"Job-ID {job_id!r} nicht gefunden in {paths.state_json}.")
        raise click.exceptions.Exit(1)
    job = state.jobs[job_id]
    job.status = status
    job.status_history.append(StatusHistoryEntry(
        status=status,
        at=_datetime.now().isoformat(timespec="seconds"),
    ))
    if application_link:
        job.application_link = application_link
    if interview_at:
        job.interview_scheduled = interview_at
    save_state(paths.state_json, state)
    click.echo(f"✔ {job_id} → {status.value}")


@main.command("note")
@click.argument("job_id")
@click.argument("text")
def cmd_note(job_id: str, text: str) -> None:
    """Fügt eine Notiz zur Bewerbung hinzu (chronologisch, je Aufruf eine neue Zeile)."""
    paths = Paths()
    state = load_state(paths.state_json)
    if job_id not in state.jobs:
        click.echo(f"Job-ID {job_id!r} nicht gefunden.")
        raise click.exceptions.Exit(1)
    job = state.jobs[job_id]
    stamp = _datetime.now().strftime("%Y-%m-%d %H:%M")
    new_entry = f"[{stamp}] {text}"
    job.notes = f"{job.notes}\n{new_entry}".strip() if job.notes else new_entry
    save_state(paths.state_json, state)
    click.echo(f"✔ Notiz hinzugefügt zu {job_id}")
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_cli_b.py -v
```

Expected: 7 passed (3 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/cli.py bewerber/tests/unit/test_cli_b.py
git commit -m "feat(cli): bewerber mark <id> <status> and bewerber note <id> commands"
```

---

## Task 14: Tailor Integration (write to state.json)

**Files:**
- Modify: `bewerber/src/bewerber/tailoring/orchestrator.py`
- Modify: `bewerber/tests/unit/test_orchestrator.py` (append)

When `bewerber tailor` runs, create or update a state.json entry: a manually-tracked job with `status=TAILORED`, populated with firma/rolle/source_url and the tailored_dir.

- [ ] **Step 1: Append test** to `bewerber/tests/unit/test_orchestrator.py`:

```python
def test_tailor_writes_state_entry(tmp_path, monkeypatch, mocker):
    """After tailor() succeeds, state.json must contain a TrackedJob with status=TAILORED."""
    workspace = tmp_path / "ws"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = tmp_path / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    _write_master(bewerber_dir).rename(bewerber_dir / "master_profile.yaml")

    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="x", berufserfahrung=[], skills_kategorisiert=SkillKategorien(),
    ))
    mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="x", einleitung="x", hauptteil="x", schluss="x", gruss="x",
    ))

    result = tailor(TailorInput(
        posting_text="job",
        firma="2b AHEAD",
        rolle="Business AI Consultant",
        datum="2026-06-12",
        kontakt_name="Frau Moser",
        source_url="https://example.com/job/abc",
        snapshot_dir=None,
        llm=mocker.Mock(),
    ))

    from bewerber.shared.state import load_state
    from bewerber.shared.state_schema import JobStatus

    state = load_state(workspace / "bewerber" / "state.json")
    # job_id should be derived from source URL when there is no scraper external_id
    matching = [j for j in state.jobs.values() if j.raw.company == "2b AHEAD"]
    assert len(matching) == 1
    job = matching[0]
    assert job.status == JobStatus.TAILORED
    assert job.raw.title.startswith("Business AI Consultant")
    assert job.tailored_dir == str(result.output_dir)
    assert job.raw.url == "https://example.com/job/abc"


def test_tailor_updates_existing_state_entry_if_url_matches(tmp_path, monkeypatch, mocker):
    """When a job already exists in state matching source_url, tailor updates it instead of creating duplicate."""
    workspace = tmp_path / "ws"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = tmp_path / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    _write_master(bewerber_dir).rename(bewerber_dir / "master_profile.yaml")

    # Pre-seed state.json with a discovered job from Arbeitsagentur with the same URL
    from bewerber.shared.state import save_state
    from bewerber.shared.state_schema import (
        BewerberState, RawJob, TrackedJob, JobStatus, Scoring,
    )
    pre = TrackedJob(
        raw=RawJob(
            board="arbeitsagentur", external_id="10001-XYZ",
            url="https://example.com/job/abc",
            title="Old title", company="Old company", location="Leipzig",
        ),
        scoring=Scoring(
            fit_score=8, begruendung="ok", matched_skills=["n8n"],
            missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
        ),
        status=JobStatus.DISCOVERED,
    )
    pre_state = BewerberState(jobs={"arbeitsagentur-10001-XYZ": pre})
    save_state(workspace / "bewerber" / "state.json", pre_state)

    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="x", berufserfahrung=[], skills_kategorisiert=SkillKategorien(),
    ))
    mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="x", einleitung="x", hauptteil="x", schluss="x", gruss="x",
    ))

    tailor(TailorInput(
        posting_text="job",
        firma="2b AHEAD",
        rolle="Business AI Consultant",
        datum="2026-06-12",
        kontakt_name=None,
        source_url="https://example.com/job/abc",
        snapshot_dir=None,
        llm=mocker.Mock(),
    ))

    from bewerber.shared.state import load_state
    state = load_state(workspace / "bewerber" / "state.json")
    # The existing arbeitsagentur job should be the only entry, now with status=TAILORED
    assert len(state.jobs) == 1
    job = list(state.jobs.values())[0]
    assert job.status == JobStatus.TAILORED
    assert job.tailored_dir
    # Original scoring preserved
    assert job.scoring.fit_score == 8
    assert "n8n" in job.scoring.matched_skills
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_orchestrator.py -v
```

Expected: 2 new tests fail.

- [ ] **Step 3: Modify `bewerber/src/bewerber/tailoring/orchestrator.py`**

Add imports near the existing ones (after `from bewerber.tailoring.render ...`):

```python
import hashlib
from bewerber.shared.state import load_state, save_state
from bewerber.shared.state_schema import (
    BewerberState, JobStatus, RawJob, StatusHistoryEntry, TrackedJob,
)
```

After the `tailoring_log.json` write block and before the final `return TailorResult(...)`, add:

```python
    _update_state_for_tailored(
        paths=paths,
        firma=inp.firma,
        rolle=inp.rolle,
        source_url=inp.source_url,
        tailored_dir=out_dir,
    )
```

Add a new private function below the `_to_german_date` function and above the markdown_it imports (or anywhere outside the existing functions):

```python
def _update_state_for_tailored(
    *,
    paths: Paths,
    firma: str,
    rolle: str,
    source_url: Optional[str],
    tailored_dir: Path,
) -> None:
    """Create or update a state.json entry for the just-tailored Bewerbung.

    Match strategy: if any existing TrackedJob has the same `raw.url` as source_url,
    update that job. Otherwise create a new manually-tracked job with board='manual'.
    """
    state = load_state(paths.state_json)

    matched_id: Optional[str] = None
    if source_url:
        for jid, job in state.jobs.items():
            if job.raw.url == source_url:
                matched_id = jid
                break

    now_iso = _now_iso_for_state()

    if matched_id is not None:
        existing = state.jobs[matched_id]
        existing.status = JobStatus.TAILORED
        existing.tailored_dir = str(tailored_dir)
        existing.status_history.append(StatusHistoryEntry(status=JobStatus.TAILORED, at=now_iso))
    else:
        external_id = (
            hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
            if source_url
            else hashlib.sha1(f"{firma}|{rolle}".encode("utf-8")).hexdigest()[:16]
        )
        new_id = f"manual-{external_id}"
        raw = RawJob(
            board="manual",
            external_id=external_id,
            url=source_url or "",
            title=rolle,
            company=firma,
            location="",
        )
        state.jobs[new_id] = TrackedJob(
            raw=raw,
            status=JobStatus.TAILORED,
            status_history=[StatusHistoryEntry(status=JobStatus.TAILORED, at=now_iso)],
            first_seen=now_iso,
            tailored_dir=str(tailored_dir),
        )

    save_state(paths.state_json, state)


def _now_iso_for_state() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")
```

- [ ] **Step 4: Run all tailoring + state tests**

```bash
pytest tests/unit/test_orchestrator.py tests/unit/test_state.py tests/unit/test_state_schema.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/tailoring/orchestrator.py bewerber/tests/unit/test_orchestrator.py
git commit -m "feat(tailoring): write state.json entry on tailor (match existing by URL)"
```

---

## Task 15: Dashboard Template (Static HTML + Inline JSON)

**Files:**
- Create: `bewerber/templates/dashboard.html.j2`

A single static HTML file with embedded CSS + vanilla-JS. State JSON is inlined into a `<script type="application/json">` tag so the page works offline via `file://`.

- [ ] **Step 1: Create `bewerber/templates/dashboard.html.j2`**

Write:

```html
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Bewerber-Dashboard</title>
<style>
* { box-sizing: border-box; }
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 14px; line-height: 1.4; color: #1a1a1a; margin: 0; padding: 16px 24px; background: #fafafa; }
h1 { font-size: 24px; margin: 0 0 8px 0; }
.meta { color: #555; font-size: 12px; margin-bottom: 16px; }
.controls { display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0; }
.controls label { font-size: 12px; color: #555; }
.controls input, .controls select { padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }
.controls input[type=search] { width: 280px; }
table { width: 100%; border-collapse: collapse; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #eee; vertical-align: top; }
th { background: #f0f0f0; font-weight: 600; cursor: pointer; user-select: none; }
th:hover { background: #e8e8e8; }
tr:hover { background: #f8f8f8; }
.score { font-weight: 700; text-align: center; min-width: 36px; }
.score-9, .score-10 { color: #1a7a1a; }
.score-7, .score-8 { color: #4a6a1a; }
.score-5, .score-6 { color: #aa7a1a; }
.score-1, .score-2, .score-3, .score-4 { color: #aa3a1a; }
.status { padding: 2px 8px; border-radius: 3px; font-size: 12px; white-space: nowrap; }
.status-discovered { background: #e8e8e8; }
.status-shortlisted { background: #d8e8f8; }
.status-tailored { background: #f8e8d8; }
.status-applied { background: #d8f0d8; }
.status-interview { background: #f0d8f8; }
.status-offer { background: #b0f0b0; font-weight: 700; }
.status-rejected { background: #f8d8d8; color: #555; }
.status-withdrawn { background: #e0e0e0; color: #777; }
.errors { background: #fff4e0; border: 1px solid #f0c890; padding: 8px 12px; margin: 12px 0; border-radius: 4px; font-size: 12px; }
.errors b { color: #aa5a00; }
.detail { display: none; padding: 12px; background: #fafafa; border-left: 3px solid #888; margin: 4px 0; }
tr.expanded + tr.detail { display: table-row; }
.detail h4 { margin: 4px 0; }
.detail .links a { display: inline-block; margin-right: 12px; }
.muted { color: #999; }
</style>
</head>
<body>
<h1>Bewerber-Dashboard</h1>
<div class="meta">
  Letzter Discovery-Run: <b>{{ state.last_discovery_run or "noch nie" }}</b> ·
  {{ state.jobs | length }} Jobs insgesamt
</div>

{% if state.scrape_errors %}
<div class="errors">
  <b>Scrape-Fehler:</b>
  {% for board, err in state.scrape_errors.items() %}
    {{ board }} ({{ err.at }}): {{ err.last_error }};
  {% endfor %}
</div>
{% endif %}

<div class="controls">
  <label>Suche: <input type="search" id="q" placeholder="Firma, Titel, Beschreibung …"></label>
  <label>Status: <select id="filter-status">
    <option value="">alle</option>
    <option value="discovered">discovered</option>
    <option value="shortlisted">shortlisted</option>
    <option value="tailored">tailored</option>
    <option value="applied">applied</option>
    <option value="interview">interview</option>
    <option value="offer">offer</option>
    <option value="rejected">rejected</option>
    <option value="withdrawn">withdrawn</option>
  </select></label>
  <label>Min Score: <select id="filter-score">
    <option value="0">alle</option>
    <option value="5">>=5</option>
    <option value="6" selected>>=6</option>
    <option value="7">>=7</option>
    <option value="8">>=8</option>
  </select></label>
  <label>Board: <select id="filter-board">
    <option value="">alle</option>
    <option value="arbeitsagentur">arbeitsagentur</option>
    <option value="linkedin">linkedin</option>
    <option value="indeed">indeed</option>
    <option value="manual">manual (tailored)</option>
  </select></label>
</div>

<table id="jobs-table">
  <thead><tr>
    <th data-sort="score">Score</th>
    <th data-sort="status">Status</th>
    <th data-sort="company">Firma</th>
    <th data-sort="title">Titel</th>
    <th data-sort="location">Ort</th>
    <th data-sort="board">Board</th>
    <th data-sort="posted_date">Veröff.</th>
  </tr></thead>
  <tbody id="jobs-tbody"></tbody>
</table>

<script id="data" type="application/json">{{ data_json }}</script>
<script>
const STATE = JSON.parse(document.getElementById("data").textContent);
const tbody = document.getElementById("jobs-tbody");
const q = document.getElementById("q");
const fStatus = document.getElementById("filter-status");
const fScore = document.getElementById("filter-score");
const fBoard = document.getElementById("filter-board");
let currentSort = { key: "score", dir: -1 };

function applyFilters() {
  const query = (q.value || "").toLowerCase();
  const minScore = parseInt(fScore.value || "0", 10);
  const statusFilter = fStatus.value;
  const boardFilter = fBoard.value;

  let rows = Object.entries(STATE.jobs).map(([jid, job]) => ({ jid, ...job }));
  rows = rows.filter(r => {
    if (statusFilter && r.status !== statusFilter) return false;
    if (boardFilter && r.raw.board !== boardFilter) return false;
    const score = (r.scoring && r.scoring.fit_score) || 0;
    if (score < minScore) return false;
    if (query) {
      const hay = [r.raw.title, r.raw.company, r.raw.location, r.raw.description || "", r.notes || ""].join(" ").toLowerCase();
      if (!hay.includes(query)) return false;
    }
    return true;
  });
  rows.sort((a, b) => {
    const key = currentSort.key;
    let av, bv;
    if (key === "score") { av = (a.scoring && a.scoring.fit_score) || 0; bv = (b.scoring && b.scoring.fit_score) || 0; }
    else if (key === "posted_date") { av = a.raw.posted_date || ""; bv = b.raw.posted_date || ""; }
    else if (key === "board") { av = a.raw.board; bv = b.raw.board; }
    else if (key === "title" || key === "company" || key === "location") { av = a.raw[key] || ""; bv = b.raw[key] || ""; }
    else { av = a[key] || ""; bv = b[key] || ""; }
    return (av < bv ? -1 : av > bv ? 1 : 0) * currentSort.dir;
  });
  renderRows(rows);
}

function renderRows(rows) {
  tbody.innerHTML = "";
  for (const r of rows) {
    const score = (r.scoring && r.scoring.fit_score) || 0;
    const tr = document.createElement("tr");
    tr.dataset.jid = r.jid;
    tr.innerHTML = `
      <td class="score score-${score}">${score || "—"}</td>
      <td><span class="status status-${r.status}">${r.status}</span></td>
      <td>${escapeHtml(r.raw.company)}</td>
      <td>${escapeHtml(r.raw.title)}</td>
      <td>${escapeHtml(r.raw.location)}</td>
      <td>${escapeHtml(r.raw.board)}</td>
      <td>${r.raw.posted_date || "—"}</td>
    `;
    tr.addEventListener("click", () => toggleDetail(tr, r));
    tbody.appendChild(tr);

    const detail = document.createElement("tr");
    detail.className = "detail";
    detail.innerHTML = `<td colspan="7">${detailHtml(r)}</td>`;
    detail.style.display = "none";
    tbody.appendChild(detail);
  }
}

function toggleDetail(tr, r) {
  const next = tr.nextElementSibling;
  if (!next || !next.classList.contains("detail")) return;
  const showing = next.style.display === "table-row";
  next.style.display = showing ? "none" : "table-row";
}

function detailHtml(r) {
  const scoring = r.scoring || {};
  const linkCv = r.tailored_dir ? `<a href="file://${r.tailored_dir}/lebenslauf.pdf">Lebenslauf PDF</a>` : "";
  const linkAns = r.tailored_dir ? `<a href="file://${r.tailored_dir}/anschreiben.pdf">Anschreiben PDF</a>` : "";
  const linkPost = r.raw.url ? `<a href="${escapeAttr(r.raw.url)}" target="_blank">Original-Posting</a>` : "";
  const linkApp = r.application_link ? `<a href="${escapeAttr(r.application_link)}" target="_blank">Eingereichte Bewerbung</a>` : "";
  const matchedSk = (scoring.matched_skills || []).map(s => `<code>${escapeHtml(s)}</code>`).join(", ");
  const missingSk = (scoring.missing_skills || []).map(s => `<code>${escapeHtml(s)}</code>`).join(", ");
  const flags = (scoring.red_flags || []).map(s => `<li>${escapeHtml(s)}</li>`).join("");
  const desc = r.raw.description ? escapeHtml(r.raw.description).slice(0, 800) + (r.raw.description.length > 800 ? "…" : "") : "<em>keine Beschreibung</em>";
  return `
    <div class="links">${linkPost} ${linkCv} ${linkAns} ${linkApp}</div>
    <h4>Scoring</h4>
    <div><b>Fit:</b> ${scoring.fit_score || "—"} — ${escapeHtml(scoring.begruendung || "")}</div>
    <div><b>Matched Skills:</b> ${matchedSk || '<span class="muted">—</span>'}</div>
    <div><b>Missing Skills:</b> ${missingSk || '<span class="muted">—</span>'}</div>
    ${flags ? `<div><b>Red Flags:</b><ul>${flags}</ul></div>` : ""}
    ${r.notes ? `<h4>Notizen</h4><pre style="white-space: pre-wrap;">${escapeHtml(r.notes)}</pre>` : ""}
    <h4>Beschreibung</h4>
    <div style="white-space: pre-wrap; font-size: 13px;">${desc}</div>
  `;
}

function escapeHtml(s) {
  s = String(s || "");
  return s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }

document.querySelectorAll("th[data-sort]").forEach(th => {
  th.addEventListener("click", () => {
    const k = th.dataset.sort;
    currentSort = { key: k, dir: currentSort.key === k ? -currentSort.dir : (k === "score" ? -1 : 1) };
    applyFilters();
  });
});
[q, fStatus, fScore, fBoard].forEach(el => el.addEventListener("input", applyFilters));
applyFilters();
</script>
</body>
</html>
```

- [ ] **Step 2: Verify template renders**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
python3 << 'EOF'
import json
from jinja2 import Environment, FileSystemLoader, select_autoescape
env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html"]))
tpl = env.get_template("dashboard.html.j2")
state = {"schema_version": 1, "last_discovery_run": None, "scrape_errors": {}, "jobs": {}}
out = tpl.render(state=type("S", (), state)(), data_json=json.dumps(state))
assert "Bewerber-Dashboard" in out
assert "noch nie" in out
print("OK")
EOF
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/templates/dashboard.html.j2
git commit -m "feat(dashboard): static HTML template with inline JSON state + client-side filters"
```

---

## Task 16: Dashboard Render + CLI

**Files:**
- Create: `bewerber/src/bewerber/dashboard/__init__.py` (empty)
- Create: `bewerber/src/bewerber/dashboard/render.py`
- Modify: `bewerber/src/bewerber/cli.py` (add `regen`, `serve`)
- Test: `bewerber/tests/unit/test_dashboard.py`
- Modify: `bewerber/tests/unit/test_cli_b.py` (append)

- [ ] **Step 1: Write failing test for render**

Write to `bewerber/tests/unit/test_dashboard.py`:

```python
import json
from pathlib import Path
from bewerber.dashboard.render import render_dashboard
from bewerber.shared.state_schema import (
    BewerberState, RawJob, TrackedJob, Scoring, JobStatus,
)


def _state_with_one_job() -> BewerberState:
    return BewerberState(
        last_discovery_run="2026-06-12T10:00:00",
        jobs={
            "arbeitsagentur-x1": TrackedJob(
                raw=RawJob(
                    board="arbeitsagentur", external_id="x1",
                    url="https://x", title="KI Manager", company="BMW",
                    location="München", description="Spannende Rolle",
                ),
                scoring=Scoring(
                    fit_score=8, begruendung="passt",
                    matched_skills=["n8n"], missing_skills=["SAP"],
                    red_flags=[], verbessern_in_anschreiben=[],
                ),
                status=JobStatus.TAILORED,
                tailored_dir="/tmp/dir",
            )
        },
    )


def test_render_dashboard_contains_inlined_state():
    html = render_dashboard(_state_with_one_job())
    assert "<title>Bewerber-Dashboard</title>" in html
    # Inlined JSON contains the job
    assert '"x1"' in html or "arbeitsagentur-x1" in html
    assert "BMW" in html
    assert "KI Manager" in html


def test_render_dashboard_shows_zero_jobs_state():
    html = render_dashboard(BewerberState())
    assert "0 Jobs" in html or "Bewerber-Dashboard" in html


def test_render_dashboard_includes_scrape_errors():
    from bewerber.shared.state_schema import ScrapeError
    state = BewerberState(scrape_errors={"linkedin": ScrapeError(last_error="rate-limited", at="2026-06-12T09:00:00")})
    html = render_dashboard(state)
    assert "linkedin" in html
    assert "rate-limited" in html
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_dashboard.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/dashboard/__init__.py`** (empty file).

- [ ] **Step 4: Implement `bewerber/src/bewerber/dashboard/render.py`**

```python
import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bewerber.shared.state_schema import BewerberState


TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"


def render_dashboard(state: BewerberState) -> str:
    """Render the static dashboard HTML from a BewerberState."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("dashboard.html.j2")
    data_json = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
    return tpl.render(state=state, data_json=data_json)
```

- [ ] **Step 5: Run, verify pass**

```bash
pytest tests/unit/test_dashboard.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Append CLI test** to `bewerber/tests/unit/test_cli_b.py`:

```python
def test_regen_writes_dashboard_html(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    _seed_state(workspace)

    runner = CliRunner()
    result = runner.invoke(main, ["regen"])
    assert result.exit_code == 0, result.output

    html = (workspace / "bewerber" / "dashboard.html").read_text(encoding="utf-8")
    assert "Bewerber-Dashboard" in html
    assert "arbeitsagentur-x1" in html


def test_serve_calls_regen_then_open(tmp_path, monkeypatch, mocker):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    _seed_state(workspace)

    fake_open = mocker.patch("bewerber.cli.webbrowser.open")
    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 0, result.output
    assert (workspace / "bewerber" / "dashboard.html").is_file()
    fake_open.assert_called_once()
    # The URL passed must be file:// pointing at the dashboard
    url = fake_open.call_args.args[0]
    assert url.startswith("file://")
    assert "dashboard.html" in url
```

- [ ] **Step 7: Update `bewerber/src/bewerber/cli.py`**

Add to imports section:

```python
import webbrowser
from bewerber.dashboard.render import render_dashboard
```

Append commands:

```python
@main.command("regen")
def cmd_regen() -> None:
    """Rendert dashboard.html aus aktuellem state.json neu."""
    paths = Paths()
    state = load_state(paths.state_json)
    html = render_dashboard(state)
    paths.dashboard_html.write_text(html, encoding="utf-8")
    click.echo(f"✔ Dashboard geschrieben: {paths.dashboard_html} ({len(state.jobs)} Jobs)")


@main.command("serve")
def cmd_serve() -> None:
    """Rendert dashboard.html und öffnet sie im Default-Browser."""
    paths = Paths()
    state = load_state(paths.state_json)
    html = render_dashboard(state)
    paths.dashboard_html.write_text(html, encoding="utf-8")
    webbrowser.open(f"file://{paths.dashboard_html}")
    click.echo(f"✔ {paths.dashboard_html} geöffnet")
```

- [ ] **Step 8: Run all tests**

```bash
pytest tests/unit/test_dashboard.py tests/unit/test_cli_b.py -v
```

Expected: 12 passed (3 dashboard + 9 cli-b).

- [ ] **Step 9: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/dashboard/ bewerber/src/bewerber/cli.py bewerber/tests/unit/test_dashboard.py bewerber/tests/unit/test_cli_b.py
git commit -m "feat(dashboard): render + bewerber regen / serve CLI commands"
```

---

## Task 17: End-to-End Integration Test

**Files:**
- Create: `bewerber/tests/integration/test_discovery_e2e.py`

Drives the full pipeline with mocked scrapers + LLM. Verifies: discover writes state, mark updates status, regen writes dashboard, dashboard contains the tracked job.

- [ ] **Step 1: Write test**

Write to `bewerber/tests/integration/test_discovery_e2e.py`:

```python
import yaml
from datetime import date
from pathlib import Path
from click.testing import CliRunner

from bewerber.cli import main
from bewerber.shared.state import load_state
from bewerber.shared.state_schema import JobStatus, RawJob, Scoring


def _setup_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "Bewerber_Assistent"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    (tmp_path / "Bewerbungsunterlagen" / "Bewerbungen").mkdir(parents=True)
    (bewerber_dir / "master_profile.yaml").write_text(yaml.safe_dump({
        "person": {"name": "Steve", "email": "s@x.de"},
        "berufsprofil": "kurz",
        "zielposition": ["KI Manager"],
    }, allow_unicode=True))
    (bewerber_dir / "searches.yaml").write_text(yaml.safe_dump({
        "defaults": {"locations": ["Leipzig"], "date_posted_max_days": 14, "min_fit_score": 6},
        "searches": [{"name": "KI", "keywords": ["KI Manager"], "boards": ["arbeitsagentur"]}],
    }, allow_unicode=True))
    return workspace


def test_full_discover_mark_regen_workflow(tmp_path, monkeypatch, mocker):
    workspace = _setup_workspace(tmp_path)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    # Mock scraper to return one job; mock enrich+score
    fake_adapter = mocker.Mock()
    fake_adapter.name = "arbeitsagentur"
    fake_adapter.search.return_value = [RawJob(
        board="arbeitsagentur", external_id="10001-1003091744-S",
        url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003091744-S",
        title="Business AI Consultant",
        company="2b AHEAD ThinkTank GmbH",
        location="Leipzig",
        posted_date=date(2026, 5, 19),
        description="Wir suchen einen erfahrenen Berater.",
        description_hash="abc123",
    )]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": fake_adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=9, begruendung="Sehr starkes Match.",
        matched_skills=["n8n", "Python"],
        missing_skills=["SAP"],
        red_flags=[],
        verbessern_in_anschreiben=[],
    ))
    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)

    runner = CliRunner()

    # 1. Discover
    r = runner.invoke(main, ["discover"])
    assert r.exit_code == 0, r.output
    assert "1 Sucheinträge" in r.output or "1 Suche" in r.output

    state = load_state(workspace / "bewerber" / "state.json")
    assert "arbeitsagentur-10001-1003091744-S" in state.jobs
    job = state.jobs["arbeitsagentur-10001-1003091744-S"]
    assert job.scoring.fit_score == 9
    assert job.status == JobStatus.DISCOVERED

    # 2. Mark as applied with link
    r = runner.invoke(main, [
        "mark", "arbeitsagentur-10001-1003091744-S", "applied",
        "--link", "https://applied.example/app123",
    ])
    assert r.exit_code == 0, r.output
    state = load_state(workspace / "bewerber" / "state.json")
    assert state.jobs["arbeitsagentur-10001-1003091744-S"].status == JobStatus.APPLIED
    assert state.jobs["arbeitsagentur-10001-1003091744-S"].application_link == "https://applied.example/app123"

    # 3. Add a note
    r = runner.invoke(main, ["note", "arbeitsagentur-10001-1003091744-S", "Recruiter heute angerufen, Termin am 19.06."])
    assert r.exit_code == 0

    # 4. Regen dashboard
    r = runner.invoke(main, ["regen"])
    assert r.exit_code == 0
    dash = (workspace / "bewerber" / "dashboard.html").read_text(encoding="utf-8")
    assert "Business AI Consultant" in dash
    assert "2b AHEAD" in dash
    assert "applied" in dash
    assert "Recruiter heute" in dash
    assert "https://applied.example/app123" in dash
```

- [ ] **Step 2: Run**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
pytest tests/integration/test_discovery_e2e.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Run full suite**

```bash
pytest -v
```

Expected: all tests pass (~115 total).

- [ ] **Step 4: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/tests/integration/test_discovery_e2e.py
git commit -m "test(discovery): end-to-end workflow integration test (discover → mark → note → regen)"
```

---

## Task 18: User Setup + First Real Discovery (user-facing)

This is the user-facing acceptance step. Steve sets up `searches.yaml` and runs a real discovery.

- [ ] **Step 1: Copy searches.yaml.example → searches.yaml and edit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
cp searches.yaml.example searches.yaml
```

Steve edits `searches.yaml` in his editor to match his actual interests (keywords, locations, boards).

- [ ] **Step 2: Register Arbeitsagentur API key**

Steve registers at https://jobsuche.api.bund.dev/, copies the API key into `bewerber/.env`:

```
ARBEITSAGENTUR_API_KEY=<his-key>
```

- [ ] **Step 3: Run real discovery**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
PYTHONPATH=src python3 -m bewerber.cli discover
```

Expected: jobs are scraped (one console line per search), scored via real LLM, written to `state.json`. Output line summarizes count + scrape errors per board if any.

- [ ] **Step 4: Open dashboard**

```bash
PYTHONPATH=src python3 -m bewerber.cli serve
```

Expected: browser opens `file:///.../bewerber/dashboard.html`, table shows scored jobs sorted by fit_score descending, filters and search work.

- [ ] **Step 5: Tailor + mark + note example**

Pick one job from the dashboard with high fit_score. Steve runs:

```bash
PYTHONPATH=src python3 -m bewerber.cli tailor \
  --url "<job url>" \
  --firma "<firma>" \
  --rolle "<rolle>" \
  --kontakt "<kontaktperson>"
```

The tailor command now also updates `state.json` to mark this job as `tailored`. Then:

```bash
PYTHONPATH=src python3 -m bewerber.cli mark "<job-id>" applied --link "<eingereichte URL>"
PYTHONPATH=src python3 -m bewerber.cli note "<job-id>" "Recruiter-Termin am ..."
PYTHONPATH=src python3 -m bewerber.cli serve
```

Dashboard now shows the entire lifecycle: scored → tailored → applied + notes.

- [ ] **Step 6: Append to `bewerber/RUNLOG.md`**

```markdown
## 2026-06-12 — Plan B first real discovery + dashboard
- Konfigurierte Suchen: <N>
- Boards: arbeitsagentur, linkedin, indeed
- Gefundene Jobs: <N>
- Tailored: <N>
- Bewerbungen abgesendet: <N>
- Dashboard offen via `bewerber serve`
```

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/RUNLOG.md
git commit -m "docs: Plan B first real discovery run log"
```

---

## Self-Review

**Spec coverage check (Subsystems 2 + 4 from design spec):**

| Spec requirement | Task |
|------------------|------|
| `searches.yaml` config with defaults + named searches | Task 4 |
| BoardAdapter protocol + per-board scraper modules | Task 5 |
| Arbeitsagentur scraper (official JSON API) | Task 6 |
| LinkedIn scraper (jobspy) | Task 7 |
| Indeed scraper (jobspy) | Task 8 |
| Enrich step (fetch HTML when description missing) | Task 9 |
| LLM scoring with fit_score + reasoning + matched/missing skills + red_flags | Task 10 |
| `discover` CLI with per-board error isolation | Tasks 11, 12 |
| `state.json` schema with status workflow | Task 2 |
| State I/O with atomic write + backup + upsert preserving curated fields | Task 3 |
| `mark <id> <status> [--link --at]` and `note <id> "..."` CLI | Task 13 |
| Status states: discovered → shortlisted → tailored → applied → interview → offer/rejected/withdrawn | Task 2 (enum) + 13 (mark) |
| Tailor integration: state entry on tailor run | Task 14 |
| Static HTML dashboard with inline JSON, filters, search, sort, detail view | Tasks 15, 16 |
| `regen` + `serve` CLI | Task 16 |
| Scrape-error banner in dashboard | Task 15 (template) |
| Direct file:// link to lebenslauf.pdf/anschreiben.pdf in detail view | Task 15 (template) |
| End-to-end integration test | Task 17 |
| User-facing real run | Task 18 |

All spec items covered ✓

**Placeholder scan:** No "TBD"/"TODO" in code. The runlog template in Task 18 has `<N>` placeholders the user fills in — that's the runtime artifact, not a plan failure.

**Type consistency:**
- `RawJob`, `Scoring`, `JobStatus`, `StatusHistoryEntry`, `TrackedJob`, `BewerberState` defined in Task 2, used across Tasks 3-17 consistently.
- `BoardAdapter` protocol in Task 5; the three scrapers in Tasks 6-8 register concrete instances into `scraper_registry`.
- `score_job(job: RawJob, master_yaml_text: str, llm: LLMClient) -> Scoring` consistent in Tasks 10, 11, 17.
- `discover(config, *, state, master_yaml_text, llm)` signature stable across Tasks 11, 12, 17.
- `LLMClient`, `Paths`, `MasterProfile` reused from Plan A without changes.
- `Paths.state_json` and `Paths.dashboard_html` added in Task 3; used in Tasks 12, 13, 16.

**Edge case caught and called out:** Task 11 explicitly handles "re-scrape with unchanged description_hash → skip rescoring" to keep LLM cost in check (real Steve will run discover daily/weekly). Tested in `test_discover_skips_rescoring_when_description_hash_unchanged`.

**Plan-aware deviation:** The spec mentions `min_fit_score` as a dashboard filter default. Task 15's dashboard template hard-codes `>=6` as the default in the score-filter dropdown. This is consistent with the `searches.yaml.example` `min_fit_score: 6`. The dropdown lets the user change it on the fly.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-12-plan-b-discovery-tracking-dashboard.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
