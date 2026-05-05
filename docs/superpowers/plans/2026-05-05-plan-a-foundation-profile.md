# Plan A — Foundation + Profil-Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation of the Bewerber-Assistent tool (Python package, CLI, schemas, LLM wrapper) and the complete Profile subsystem, enabling Steve to generate a validated `master_profile.yaml` from his existing Bewerbungsunterlagen and 17 project folders.

**Architecture:** Python 3.11+ package `bewerber/` under `/Users/steve/Documents/Bewerber_Assistent/`, Click-based CLI, pydantic v2 schemas, OpenAI structured outputs for LLM calls. Three CLI commands deliver the full profile workflow: `projects scan` (folders → `_profile.md`), `profile sync` (markdown → YAML), `profile init` (Bewerbungsunterlagen → YAML).

**Tech Stack:** Python 3.11+, Click, pydantic v2, PyYAML, python-frontmatter, pdfplumber (PDF text), python-docx (DOCX text), openai (LLM), python-dotenv, pytest, pytest-mock.

**Spec reference:** [docs/superpowers/specs/2026-05-04-bewerber-assistent-design.md](../specs/2026-05-04-bewerber-assistent-design.md), Subsystem 1.

---

## File Structure (Plan A)

```
/Users/steve/Documents/Bewerber_Assistent/
├── .gitignore                                  # excludes scope/, secrets, generated state
├── bewerber/
│   ├── pyproject.toml
│   ├── README.md
│   ├── .env.example
│   ├── src/bewerber/
│   │   ├── __init__.py
│   │   ├── cli.py                              # Click entry, command groups
│   │   ├── shared/
│   │   │   ├── __init__.py
│   │   │   ├── paths.py                        # central path constants
│   │   │   ├── profile_schema.py               # pydantic models for master_profile.yaml
│   │   │   ├── document.py                     # PDF/DOCX → text
│   │   │   └── llm.py                          # OpenAI structured outputs wrapper
│   │   └── profile/
│   │       ├── __init__.py
│   │       ├── projects.py                     # folder scan → _profile.md
│   │       ├── sync.py                         # _profile.md → master_profile.yaml
│   │       └── extractor.py                    # Bewerbungsunterlagen → master_profile.yaml
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── unit/
│       │   ├── test_profile_schema.py
│       │   ├── test_paths.py
│       │   ├── test_document.py
│       │   ├── test_llm.py
│       │   ├── test_projects.py
│       │   └── test_sync.py
│       ├── integration/
│       │   └── test_extractor.py
│       └── fixtures/
│           ├── sample_project_folder/
│           │   ├── README.md
│           │   └── main.py
│           ├── sample_resume.pdf
│           └── sample.docx
```

**File responsibilities:**
- `cli.py`: Only argument parsing + dispatch. Business logic lives in modules.
- `shared/`: Cross-subsystem utilities (used by Plan A, B, C).
- `profile/`: Profile-Aufbau subsystem only.

---

## Task 1: Project Skeleton + Git Init

**Files:**
- Create: `/Users/steve/Documents/Bewerber_Assistent/.gitignore`
- Create: `bewerber/pyproject.toml`
- Create: `bewerber/.env.example`
- Create: `bewerber/README.md`
- Create: `bewerber/src/bewerber/__init__.py`
- Create: `bewerber/tests/__init__.py`
- Create: `bewerber/tests/conftest.py`

- [ ] **Step 1: Initialize git repo at workspace root**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git init
```

Expected: "Initialized empty Git repository in .../.git/"

- [ ] **Step 2: Create root `.gitignore`**

Write to `/Users/steve/Documents/Bewerber_Assistent/.gitignore`:

```gitignore
# Cloned reference repos (not part of this project)
scope/

# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.coverage
htmlcov/

# Environment & secrets
.env
.env.local

# Personal data (user-specific, generated)
bewerber/master_profile.yaml
bewerber/state.json
bewerber/state.json.bak
bewerber/anschreiben_examples/
bewerber/dashboard.html

# OS
.DS_Store
```

- [ ] **Step 3: Create `bewerber/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "bewerber"
version = "0.1.0"
description = "Personal job-application assistant: profile extraction, job discovery, tailoring, dashboard"
requires-python = ">=3.11"
dependencies = [
    "click>=8.1",
    "pydantic>=2.5",
    "pyyaml>=6.0",
    "python-frontmatter>=1.0",
    "pdfplumber>=0.10",
    "python-docx>=1.1",
    "openai>=1.40",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "pytest-cov>=4.1",
]

[project.scripts]
bewerber = "bewerber.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/bewerber"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 4: Create `bewerber/.env.example`**

```
# OpenAI API key for LLM calls (gpt-5.1-mini)
OPENAI_API_KEY=sk-...

# Optional: override default LLM model
BEWERBER_LLM_MODEL=gpt-5.1-mini

# Arbeitsagentur API key (for Plan B; not needed for Plan A)
ARBEITSAGENTUR_API_KEY=
```

- [ ] **Step 5: Create `bewerber/README.md`**

```markdown
# bewerber

Persönliches Bewerber-Werkzeug: Profil-Aufbau, Job-Discovery, Tailoring, Dashboard.

## Setup

```bash
cd bewerber
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# .env editieren: OPENAI_API_KEY eintragen
```

## Commands

Plan A (verfügbar):
- `bewerber projects scan` — generiert `_profile.md` in jedem Projektordner
- `bewerber profile sync` — `_profile.md` → `master_profile.yaml`
- `bewerber profile init` — `Bewerbungsunterlagen/` → `master_profile.yaml`

Plan B + C: folgen.
```

- [ ] **Step 6: Create `bewerber/src/bewerber/__init__.py` and `bewerber/tests/__init__.py`**

Both files: empty (just `touch`).

- [ ] **Step 7: Create `bewerber/tests/conftest.py`**

```python
import os
import pytest
from pathlib import Path


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def disable_real_openai(monkeypatch):
    """Prevent accidental real LLM calls in unit tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
```

- [ ] **Step 8: Install package in editable mode**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: "Successfully installed bewerber-0.1.0 ..." (system has Python 3.12, satisfies `>=3.11`)

- [ ] **Step 9: Verify pytest discovers (no tests yet, should report 0)**

```bash
pytest -v
```

Expected: "no tests ran" or "collected 0 items"

- [ ] **Step 10: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add .gitignore docs/ bewerber/pyproject.toml bewerber/README.md bewerber/.env.example bewerber/src/bewerber/__init__.py bewerber/tests/__init__.py bewerber/tests/conftest.py
git commit -m "chore: project skeleton (bewerber package, pytest, git init)"
```

---

## Task 2: Profile Pydantic Schema

**Files:**
- Create: `bewerber/src/bewerber/shared/__init__.py` (empty)
- Create: `bewerber/src/bewerber/shared/profile_schema.py`
- Test: `bewerber/tests/unit/test_profile_schema.py`

- [ ] **Step 1: Create `tests/unit/__init__.py` (empty)** and write the failing test

Write to `bewerber/tests/unit/test_profile_schema.py`:

```python
import pytest
import yaml
from pydantic import ValidationError
from bewerber.shared.profile_schema import MasterProfile, Project, Berufserfahrung


def test_minimal_valid_profile():
    data = {
        "person": {"name": "Steve Eigenwillig", "email": "s@example.com"},
        "berufsprofil": "Erfahrener Projektmanager mit Fokus auf KI-Automatisierung.",
        "zielposition": ["KI Manager", "Lead Projektmanager"],
        "ausbildung": [],
        "berufserfahrung": [],
        "projekte": [],
    }
    profile = MasterProfile(**data)
    assert profile.person.name == "Steve Eigenwillig"
    assert "KI Manager" in profile.zielposition


def test_project_requires_id_and_titel():
    with pytest.raises(ValidationError):
        Project(titel="x")  # id missing


def test_berufserfahrung_bis_optional():
    job = Berufserfahrung(
        position="PM",
        firma="Acme",
        von="2020-03",
        bis=None,
        aufgaben=[],
        erfolge=[],
        skills=[],
    )
    assert job.bis is None


def test_yaml_roundtrip(tmp_path):
    data = {
        "person": {"name": "X", "email": "x@y.de"},
        "berufsprofil": "kurz",
        "zielposition": ["A"],
        "ausbildung": [],
        "berufserfahrung": [],
        "projekte": [
            {
                "id": "8-n8n-builder",
                "titel": "n8n Builder",
                "kurzbeschreibung": "k",
                "rolle": "r",
                "skills_fachlich": ["Python"],
                "skills_methodisch": [],
                "sichtbar_in_lebenslauf": True,
            }
        ],
    }
    profile = MasterProfile(**data)
    f = tmp_path / "p.yaml"
    f.write_text(yaml.safe_dump(profile.model_dump(), allow_unicode=True))
    loaded = MasterProfile(**yaml.safe_load(f.read_text()))
    assert loaded.projekte[0].id == "8-n8n-builder"
```

- [ ] **Step 2: Run test, verify fail**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
pytest tests/unit/test_profile_schema.py -v
```

Expected: ImportError / ModuleNotFoundError for `bewerber.shared.profile_schema`.

- [ ] **Step 3: Create `bewerber/src/bewerber/shared/__init__.py`** (empty file).

- [ ] **Step 4: Implement `bewerber/src/bewerber/shared/profile_schema.py`**

```python
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    email: EmailStr
    phone: Optional[str] = None
    adresse: Optional[str] = None
    linkedin: Optional[str] = None
    xing: Optional[str] = None
    github: Optional[str] = None


class Arbeitspraeferenzen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    remote: Optional[str] = None  # "ja" | "teilweise" | "nein"
    reisebereitschaft: Optional[str] = None
    gehaltserwartung_brutto_jahr: Optional[str] = None
    notice_period: Optional[str] = None


class Ausbildung(BaseModel):
    model_config = ConfigDict(extra="forbid")
    art: str
    institution: str
    abschluss: Optional[str] = None
    jahr: Optional[str] = None
    nachweis_pdf: Optional[str] = None


class Berufserfahrung(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: str
    firma: str
    von: str  # YYYY-MM
    bis: Optional[str] = None  # YYYY-MM or None for current
    standort: Optional[str] = None
    aufgaben: list[str] = Field(default_factory=list)
    erfolge: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    nachweis_pdf: Optional[str] = None


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    titel: str
    quelle: Optional[str] = None
    kurzbeschreibung: Optional[str] = None
    rolle: Optional[str] = None
    skills_fachlich: list[str] = Field(default_factory=list)
    skills_methodisch: list[str] = Field(default_factory=list)
    erfolge: list[str] = Field(default_factory=list)
    sichtbar_in_lebenslauf: bool = True


class Zertifikat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    aussteller: Optional[str] = None
    jahr: Optional[str] = None


class Sprache(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sprache: str
    niveau: str  # z.B. "Muttersprache", "C1", "B2"


class MasterProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person: Person
    berufsprofil: str
    zielposition: list[str] = Field(default_factory=list)
    arbeitspraeferenzen: Optional[Arbeitspraeferenzen] = None
    ausbildung: list[Ausbildung] = Field(default_factory=list)
    berufserfahrung: list[Berufserfahrung] = Field(default_factory=list)
    projekte: list[Project] = Field(default_factory=list)
    zertifikate: list[Zertifikat] = Field(default_factory=list)
    sprachen: list[Sprache] = Field(default_factory=list)
    interessen: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Run test, verify pass**

```bash
pytest tests/unit/test_profile_schema.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add bewerber/src/bewerber/shared/ bewerber/tests/unit/__init__.py bewerber/tests/unit/test_profile_schema.py
git commit -m "feat(profile): pydantic schema for master_profile.yaml"
```

---

## Task 3: Path Constants

**Files:**
- Create: `bewerber/src/bewerber/shared/paths.py`
- Test: `bewerber/tests/unit/test_paths.py`

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_paths.py`:

```python
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


def test_project_folders_filter(monkeypatch, tmp_path):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 Kleinanzeigen").mkdir()
    (tmp_path / "11 MerchApp").mkdir()
    (tmp_path / "Bewerbungsunterlagen").mkdir()
    (tmp_path / "random_file.pdf").touch()
    p = Paths()
    folders = sorted(f.name for f in p.project_folders())
    assert folders == ["1 Kleinanzeigen", "11 MerchApp"]
```

- [ ] **Step 2: Run test, verify fail**

```bash
pytest tests/unit/test_paths.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/shared/paths.py`**

```python
import os
import re
from pathlib import Path


class Paths:
    """Central path configuration. Allows override via env vars for testing."""

    PROJECT_FOLDER_REGEX = re.compile(r"^\d+\s+.+")

    def __init__(self) -> None:
        self.workspace = Path(
            os.environ.get(
                "BEWERBER_WORKSPACE", "/Users/steve/Documents/Bewerber_Assistent"
            )
        )
        self.documents = Path(
            os.environ.get("BEWERBER_DOCUMENTS", "/Users/steve/Documents")
        )

    @property
    def bewerber_dir(self) -> Path:
        return self.workspace / "bewerber"

    @property
    def master_profile(self) -> Path:
        return self.bewerber_dir / "master_profile.yaml"

    @property
    def bewerbungsunterlagen(self) -> Path:
        return self.documents / "Bewerbungsunterlagen"

    @property
    def bewerbungen(self) -> Path:
        return self.bewerbungsunterlagen / "Bewerbungen"

    @property
    def anschreiben_examples(self) -> Path:
        return self.bewerber_dir / "anschreiben_examples"

    def project_folders(self) -> list[Path]:
        """Return sorted list of folders matching `<number> <name>` pattern."""
        if not self.documents.is_dir():
            return []
        return sorted(
            p
            for p in self.documents.iterdir()
            if p.is_dir() and self.PROJECT_FOLDER_REGEX.match(p.name)
        )
```

- [ ] **Step 4: Run test, verify pass**

```bash
pytest tests/unit/test_paths.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add bewerber/src/bewerber/shared/paths.py bewerber/tests/unit/test_paths.py
git commit -m "feat(shared): central Paths configuration with env-var overrides"
```

---

## Task 4: LLM Wrapper (OpenAI Structured Outputs)

**Files:**
- Create: `bewerber/src/bewerber/shared/llm.py`
- Test: `bewerber/tests/unit/test_llm.py`

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_llm.py`:

```python
from pydantic import BaseModel
from bewerber.shared.llm import LLMClient


class DummyOut(BaseModel):
    answer: str
    score: int


def test_structured_call_uses_responses_parse(mocker):
    fake_client = mocker.Mock()
    fake_resp = mocker.Mock()
    fake_resp.output_parsed = DummyOut(answer="hello", score=7)
    fake_client.responses.parse.return_value = fake_resp

    client = LLMClient(client=fake_client, model="gpt-test")
    result = client.structured(
        system="be helpful",
        user="hi",
        schema=DummyOut,
    )
    assert result.answer == "hello"
    assert result.score == 7
    fake_client.responses.parse.assert_called_once()
    call_kwargs = fake_client.responses.parse.call_args.kwargs
    assert call_kwargs["model"] == "gpt-test"
    assert call_kwargs["text_format"] == DummyOut


def test_text_call(mocker):
    fake_client = mocker.Mock()
    fake_resp = mocker.Mock()
    fake_resp.output_text = "plain answer"
    fake_client.responses.create.return_value = fake_resp

    client = LLMClient(client=fake_client, model="gpt-test")
    result = client.text(system="s", user="u")
    assert result == "plain answer"


def test_default_model_from_env(monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_LLM_MODEL", "gpt-from-env")
    fake_openai = mocker.patch("bewerber.shared.llm.OpenAI")
    client = LLMClient()
    assert client.model == "gpt-from-env"
    fake_openai.assert_called_once()
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_llm.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/shared/llm.py`**

```python
import os
from typing import Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Thin wrapper around OpenAI Responses API with structured outputs."""

    DEFAULT_MODEL = "gpt-5.1-mini"

    def __init__(self, client: OpenAI | None = None, model: str | None = None) -> None:
        self.client = client or OpenAI()
        self.model = model or os.environ.get("BEWERBER_LLM_MODEL", self.DEFAULT_MODEL)

    def structured(self, *, system: str, user: str, schema: Type[T]) -> T:
        """Call LLM with a pydantic schema as required output format."""
        resp = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=schema,
        )
        return resp.output_parsed

    def text(self, *, system: str, user: str) -> str:
        """Call LLM for free-form text output (e.g. cover letters)."""
        resp = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.output_text
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_llm.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add bewerber/src/bewerber/shared/llm.py bewerber/tests/unit/test_llm.py
git commit -m "feat(shared): LLMClient wrapper with structured-output and text APIs"
```

---

## Task 5: Document Reader (PDF + DOCX → Text)

**Files:**
- Create: `bewerber/src/bewerber/shared/document.py`
- Test: `bewerber/tests/unit/test_document.py`
- Test fixtures: `bewerber/tests/fixtures/sample_resume.pdf`, `bewerber/tests/fixtures/sample.docx` (generated in Step 1)

- [ ] **Step 1: Generate test fixtures**

Run inline Python to create real PDF and DOCX fixtures (so we test actual libraries):

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
mkdir -p tests/fixtures
python3 -c "
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
c = canvas.Canvas('tests/fixtures/sample_resume.pdf', pagesize=A4)
c.drawString(100, 800, 'Lebenslauf Steve Eigenwillig')
c.drawString(100, 780, 'Email: s.eigenwillig@example.com')
c.drawString(100, 760, 'Erfahrung: Projektmanager 2020-2024')
c.save()
" 2>&1 || pip install reportlab && python3 -c "
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
c = canvas.Canvas('tests/fixtures/sample_resume.pdf', pagesize=A4)
c.drawString(100, 800, 'Lebenslauf Steve Eigenwillig')
c.drawString(100, 780, 'Email: s.eigenwillig@example.com')
c.drawString(100, 760, 'Erfahrung: Projektmanager 2020-2024')
c.save()
"

python3 -c "
from docx import Document
d = Document()
d.add_heading('Anschreiben', 0)
d.add_paragraph('Sehr geehrte Damen und Herren,')
d.add_paragraph('hiermit bewerbe ich mich auf die Position als Projektmanager.')
d.save('tests/fixtures/sample.docx')
"
```

Expected: Files `tests/fixtures/sample_resume.pdf` and `tests/fixtures/sample.docx` exist.

- [ ] **Step 2: Add reportlab as dev dep** in `pyproject.toml`

Modify `bewerber/pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "pytest-cov>=4.1",
    "reportlab>=4.0",
]
```

Then `pip install -e ".[dev]"` to apply.

- [ ] **Step 3: Write failing test**

Write to `bewerber/tests/unit/test_document.py`:

```python
from pathlib import Path
from bewerber.shared.document import read_document_text


def test_read_pdf(fixtures_dir: Path):
    text = read_document_text(fixtures_dir / "sample_resume.pdf")
    assert "Steve Eigenwillig" in text
    assert "s.eigenwillig@example.com" in text


def test_read_docx(fixtures_dir: Path):
    text = read_document_text(fixtures_dir / "sample.docx")
    assert "Sehr geehrte Damen und Herren" in text
    assert "Projektmanager" in text


def test_unsupported_format_raises(tmp_path):
    f = tmp_path / "x.xyz"
    f.write_text("nope")
    try:
        read_document_text(f)
    except ValueError as e:
        assert "unsupported" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")


def test_missing_file_raises(tmp_path):
    try:
        read_document_text(tmp_path / "nope.pdf")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")
```

- [ ] **Step 4: Run, verify fail**

```bash
pytest tests/unit/test_document.py -v
```

Expected: ImportError.

- [ ] **Step 5: Implement `bewerber/src/bewerber/shared/document.py`**

```python
from pathlib import Path
import pdfplumber
from docx import Document


def read_document_text(path: Path) -> str:
    """Extract plain text from a PDF or DOCX file."""
    if not path.exists():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    raise ValueError(f"Unsupported format: {suffix}")


def _read_pdf(path: Path) -> str:
    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt:
                parts.append(txt)
    return "\n".join(parts)


def _read_docx(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text)
```

- [ ] **Step 6: Run, verify pass**

```bash
pytest tests/unit/test_document.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add bewerber/src/bewerber/shared/document.py bewerber/tests/unit/test_document.py bewerber/tests/fixtures/sample_resume.pdf bewerber/tests/fixtures/sample.docx bewerber/pyproject.toml
git commit -m "feat(shared): document reader for PDF and DOCX"
```

---

## Task 6: CLI Scaffold

**Files:**
- Create: `bewerber/src/bewerber/cli.py`
- Test: `bewerber/tests/unit/test_cli.py`

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_cli.py`:

```python
from click.testing import CliRunner
from bewerber.cli import main


def test_cli_help_lists_command_groups():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "profile" in result.output
    assert "projects" in result.output


def test_profile_help_lists_subcommands():
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "sync" in result.output


def test_projects_help_lists_scan():
    runner = CliRunner()
    result = runner.invoke(main, ["projects", "--help"])
    assert result.exit_code == 0
    assert "scan" in result.output
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement minimal CLI scaffold `bewerber/src/bewerber/cli.py`**

```python
import click
from dotenv import load_dotenv

load_dotenv()


@click.group()
def main() -> None:
    """Bewerber-Assistent: Profil, Discovery, Tailoring, Dashboard."""


@main.group()
def profile() -> None:
    """Profil-Aufbau und -Pflege."""


@main.group()
def projects() -> None:
    """Projektordner-Management."""


@profile.command("init")
def profile_init() -> None:
    """Erzeugt master_profile.yaml aus Bewerbungsunterlagen/."""
    click.echo("not yet implemented")
    raise click.exceptions.Exit(2)


@profile.command("sync")
def profile_sync() -> None:
    """Merged _profile.md aus Projektordnern in master_profile.yaml."""
    click.echo("not yet implemented")
    raise click.exceptions.Exit(2)


@projects.command("scan")
@click.option("--force", is_flag=True, help="Überschreibe bestehende _profile.md")
def projects_scan(force: bool) -> None:
    """Erzeugt _profile.md in jedem Projektordner."""
    click.echo(f"not yet implemented (force={force})")
    raise click.exceptions.Exit(2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Verify CLI binary works**

```bash
bewerber --help
bewerber profile --help
bewerber projects --help
```

Expected: each shows help text without error.

- [ ] **Step 6: Commit**

```bash
git add bewerber/src/bewerber/cli.py bewerber/tests/unit/test_cli.py
git commit -m "feat(cli): scaffold with profile and projects command groups"
```

---

## Task 7: Project Scanner (folder → `_profile.md`)

**Files:**
- Create: `bewerber/src/bewerber/profile/__init__.py` (empty)
- Create: `bewerber/src/bewerber/profile/projects.py`
- Test: `bewerber/tests/unit/test_projects.py`
- Fixture: `bewerber/tests/fixtures/sample_project_folder/`

- [ ] **Step 1: Create test fixtures**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
mkdir -p tests/fixtures/sample_project_folder
cat > tests/fixtures/sample_project_folder/README.md << 'EOF'
# n8n Builder

A workflow automation tool built on top of n8n. Connects to Freshdesk,
processes tickets, generates AI summaries via OpenAI.

## Stack
- Python 3.11
- n8n
- OpenAI API
EOF

cat > tests/fixtures/sample_project_folder/main.py << 'EOF'
def process_ticket(ticket_id: str) -> dict:
    """Process a Freshdesk ticket and return summary."""
    return {"id": ticket_id, "summary": "..."}
EOF
```

- [ ] **Step 2: Write failing test**

Write to `bewerber/tests/unit/test_projects.py`:

```python
import frontmatter
from pathlib import Path
from bewerber.profile.projects import scan_project, gather_project_context, ProjectDraft


def test_gather_context_reads_readme_and_code(fixtures_dir: Path):
    folder = fixtures_dir / "sample_project_folder"
    ctx = gather_project_context(folder, max_chars=10000)
    assert "n8n Builder" in ctx
    assert "Freshdesk" in ctx
    assert "process_ticket" in ctx


def test_gather_context_truncates_at_limit(tmp_path):
    folder = tmp_path / "1 Big"
    folder.mkdir()
    (folder / "README.md").write_text("X" * 5000)
    (folder / "code.py").write_text("Y" * 5000)
    ctx = gather_project_context(folder, max_chars=2000)
    assert len(ctx) <= 2000


def test_scan_project_writes_profile_md(tmp_path, mocker):
    folder = tmp_path / "8 n8n_builder"
    folder.mkdir()
    (folder / "README.md").write_text("# n8n Builder\nWorkflow automation.")

    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ProjectDraft(
        kurzbeschreibung="Workflow tool.",
        rolle="Hauptentwickler.",
        skills_fachlich=["Python", "n8n"],
        skills_methodisch=["Agile"],
        erfolge=["Reduzierte Aufwand um 50%"],
    )

    out_path = scan_project(folder, llm=fake_llm, force=False)
    assert out_path == folder / "_profile.md"
    assert out_path.exists()
    post = frontmatter.load(str(out_path))
    assert post["id"] == "8-n8n-builder"
    assert post["titel"] == "n8n Builder"
    assert post["sichtbar_in_lebenslauf"] is True
    assert "Workflow tool." in post.content
    assert "Python" in post.content
    assert "Agile" in post.content


def test_scan_project_skips_existing_without_force(tmp_path, mocker):
    folder = tmp_path / "1 Existing"
    folder.mkdir()
    (folder / "_profile.md").write_text("---\nid: x\n---\noriginal")

    fake_llm = mocker.Mock()
    out = scan_project(folder, llm=fake_llm, force=False)
    assert out is None
    fake_llm.structured.assert_not_called()


def test_scan_project_overwrites_with_force(tmp_path, mocker):
    folder = tmp_path / "1 Existing"
    folder.mkdir()
    (folder / "README.md").write_text("# Existing")
    (folder / "_profile.md").write_text("---\nid: x\n---\noriginal")

    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ProjectDraft(
        kurzbeschreibung="new",
        rolle="r",
        skills_fachlich=[],
        skills_methodisch=[],
        erfolge=[],
    )
    out = scan_project(folder, llm=fake_llm, force=True)
    assert out is not None
    content = out.read_text()
    assert "new" in content
    assert "original" not in content


def test_id_slug_from_folder_name():
    from bewerber.profile.projects import folder_to_id
    assert folder_to_id("8 n8n_builder") == "8-n8n-builder"
    assert folder_to_id("1 Kleinanzeigen") == "1-kleinanzeigen"
    assert folder_to_id("16 API Gateway") == "16-api-gateway"
```

- [ ] **Step 3: Run, verify fail**

```bash
pytest tests/unit/test_projects.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `bewerber/src/bewerber/profile/__init__.py`** (empty file).

- [ ] **Step 5: Implement `bewerber/src/bewerber/profile/projects.py`**

```python
import re
from pathlib import Path
from typing import Optional
import frontmatter
from pydantic import BaseModel, Field

from bewerber.shared.llm import LLMClient


PROFILE_FILENAME = "_profile.md"

PRIORITY_FILES = ["README.md", "readme.md", "claude.md", "CLAUDE.md"]
EXTENSIONS_TO_SAMPLE = {".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".txt"}
MAX_FILE_BYTES = 50_000

SYSTEM_PROMPT = """Du bist ein Karriere-Coach. Du analysierst einen Projektordner und extrahierst die fachlichen Inhalte für einen Lebenslauf-Eintrag.
Antworte ausschließlich auf Deutsch. Keine Erfindungen — nur Inhalte aus dem gegebenen Material.
Wenn etwas unklar ist, formuliere es als Frage in der Kurzbeschreibung statt es zu erfinden."""


class ProjectDraft(BaseModel):
    kurzbeschreibung: str = Field(description="2-3 Sätze: Was ist das Projekt?")
    rolle: str = Field(description="Was war wahrscheinlich der Beitrag des Eigentümers?")
    skills_fachlich: list[str] = Field(description="Technische Skills: Sprachen, Tools, Frameworks")
    skills_methodisch: list[str] = Field(description="Methoden: Agile, Workflow-Design, etc.")
    erfolge: list[str] = Field(description="Konkrete Outcomes — leer lassen wenn nicht aus Material erkennbar")


def folder_to_id(folder_name: str) -> str:
    """`8 n8n_builder` → `8-n8n-builder`"""
    s = folder_name.strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def folder_to_title(folder_name: str) -> str:
    """`8 n8n_builder` → `n8n_builder` (number stripped)."""
    return re.sub(r"^\d+\s+", "", folder_name)


def gather_project_context(folder: Path, max_chars: int) -> str:
    """Read prioritized files from folder, concatenate, truncate at max_chars."""
    parts: list[str] = []
    used = 0

    files_in_priority = []
    for name in PRIORITY_FILES:
        f = folder / name
        if f.is_file():
            files_in_priority.append(f)

    other_files = [
        f
        for f in folder.rglob("*")
        if f.is_file()
        and f.suffix.lower() in EXTENSIONS_TO_SAMPLE
        and f not in files_in_priority
        and f.name != PROFILE_FILENAME
        and not any(part.startswith(".") for part in f.parts)
    ]
    files_in_priority.extend(sorted(other_files, key=lambda p: p.stat().st_size))

    parts.append(f"Folder name: {folder.name}\n")
    parts.append("File listing:")
    for f in files_in_priority[:50]:
        try:
            rel = f.relative_to(folder)
        except ValueError:
            rel = f
        parts.append(f"  {rel}")
    parts.append("")

    for f in files_in_priority:
        if used >= max_chars:
            break
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")[:MAX_FILE_BYTES]
        except OSError:
            continue
        header = f"\n--- {f.relative_to(folder)} ---\n"
        chunk = header + content
        remaining = max_chars - used
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        parts.append(chunk)
        used += len(chunk)

    full = "\n".join(parts)
    return full[:max_chars]


def scan_project(
    folder: Path,
    llm: LLMClient,
    force: bool = False,
    max_chars: int = 30_000,
) -> Optional[Path]:
    """Generate `_profile.md` for one project folder. Returns path or None if skipped."""
    out = folder / PROFILE_FILENAME
    if out.exists() and not force:
        return None

    context = gather_project_context(folder, max_chars=max_chars)
    user_prompt = f"Projektordner-Inhalt:\n\n{context}"

    draft = llm.structured(
        system=SYSTEM_PROMPT, user=user_prompt, schema=ProjectDraft
    )

    body = _render_markdown(draft)
    post = frontmatter.Post(
        body,
        id=folder_to_id(folder.name),
        titel=folder_to_title(folder.name),
        sichtbar_in_lebenslauf=True,
    )
    out.write_text(frontmatter.dumps(post), encoding="utf-8")
    return out


def _render_markdown(draft: ProjectDraft) -> str:
    def bullet_list(items: list[str]) -> str:
        return "\n".join(f"- {x}" for x in items) if items else "- (leer)"

    return f"""## Kurzbeschreibung
{draft.kurzbeschreibung}

## Meine Rolle / Beitrag
{draft.rolle}

## Fachliche Skills
{bullet_list(draft.skills_fachlich)}

## Methodische Skills
{bullet_list(draft.skills_methodisch)}

## Erfolge / Outcomes
{bullet_list(draft.erfolge)}

## Notizen (nicht im Lebenslauf)

"""
```

- [ ] **Step 6: Run, verify pass**

```bash
pytest tests/unit/test_projects.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add bewerber/src/bewerber/profile/ bewerber/tests/unit/test_projects.py bewerber/tests/fixtures/sample_project_folder/
git commit -m "feat(profile): project scanner generates _profile.md from folder content"
```

---

## Task 8: Wire `bewerber projects scan` Command

**Files:**
- Modify: `bewerber/src/bewerber/cli.py`
- Test: `bewerber/tests/unit/test_cli.py` (extend)

- [ ] **Step 1: Extend test**

Append to `bewerber/tests/unit/test_cli.py`:

```python
def test_projects_scan_iterates_folders(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 First").mkdir()
    (tmp_path / "1 First" / "README.md").write_text("# First")
    (tmp_path / "2 Second").mkdir()
    (tmp_path / "2 Second" / "README.md").write_text("# Second")
    (tmp_path / "ignored.txt").touch()

    fake_scan = mocker.patch("bewerber.cli.scan_project")
    fake_scan.return_value = tmp_path / "1 First" / "_profile.md"
    mocker.patch("bewerber.cli.LLMClient")

    runner = CliRunner()
    result = runner.invoke(main, ["projects", "scan"])
    assert result.exit_code == 0, result.output
    assert fake_scan.call_count == 2


def test_projects_scan_passes_force_flag(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 X").mkdir()
    fake_scan = mocker.patch("bewerber.cli.scan_project")
    mocker.patch("bewerber.cli.LLMClient")

    runner = CliRunner()
    result = runner.invoke(main, ["projects", "scan", "--force"])
    assert result.exit_code == 0
    _, kwargs = fake_scan.call_args
    assert kwargs.get("force") is True
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 2 new tests fail (`scan_project` is not imported in cli yet).

- [ ] **Step 3: Update `bewerber/src/bewerber/cli.py`**

Replace the `projects_scan` function and add imports. Modify the imports section at top:

```python
import click
from dotenv import load_dotenv

from bewerber.profile.projects import scan_project
from bewerber.shared.llm import LLMClient
from bewerber.shared.paths import Paths
```

Replace `projects_scan`:

```python
@projects.command("scan")
@click.option("--force", is_flag=True, help="Überschreibe bestehende _profile.md")
def projects_scan(force: bool) -> None:
    """Erzeugt _profile.md in jedem Projektordner."""
    paths = Paths()
    llm = LLMClient()
    folders = paths.project_folders()
    if not folders:
        click.echo(f"Keine Projektordner gefunden in {paths.documents}")
        return
    click.echo(f"Scanne {len(folders)} Projektordner …")
    for folder in folders:
        result = scan_project(folder, llm=llm, force=force)
        if result is None:
            click.echo(f"  skip (existiert): {folder.name}")
        else:
            click.echo(f"  ok:  {folder.name} → {result.name}")
    click.echo("Fertig.")
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add bewerber/src/bewerber/cli.py bewerber/tests/unit/test_cli.py
git commit -m "feat(cli): wire projects scan command to scan_project"
```

---

## Task 9: Profile Sync (`_profile.md` → `master_profile.yaml`)

**Files:**
- Create: `bewerber/src/bewerber/profile/sync.py`
- Test: `bewerber/tests/unit/test_sync.py`

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_sync.py`:

```python
import yaml
from pathlib import Path
from bewerber.profile.sync import sync_projects_into_profile, parse_profile_md


def _make_md(tmp_path: Path, name: str, body_dict: dict) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    fm = "\n".join(f"{k}: {v}" for k, v in body_dict.items())
    body = """## Kurzbeschreibung
Eine Beschreibung.

## Meine Rolle / Beitrag
Hauptentwickler.

## Fachliche Skills
- Python
- n8n

## Methodische Skills
- Agile

## Erfolge / Outcomes
- Erfolg X

## Notizen (nicht im Lebenslauf)
private kram
"""
    (folder / "_profile.md").write_text(f"---\n{fm}\n---\n{body}")
    return folder


def test_parse_profile_md(tmp_path):
    folder = _make_md(tmp_path, "1 Test", {"id": "1-test", "titel": "Test", "sichtbar_in_lebenslauf": True})
    project = parse_profile_md(folder / "_profile.md")
    assert project.id == "1-test"
    assert project.titel == "Test"
    assert project.sichtbar_in_lebenslauf is True
    assert project.kurzbeschreibung == "Eine Beschreibung."
    assert project.rolle == "Hauptentwickler."
    assert "Python" in project.skills_fachlich
    assert "Agile" in project.skills_methodisch
    assert "Erfolg X" in project.erfolge


def test_sync_creates_master_yaml_with_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path / "workspace"))
    (tmp_path / "workspace" / "bewerber").mkdir(parents=True)

    _make_md(tmp_path, "1 Alpha", {"id": "1-alpha", "titel": "Alpha", "sichtbar_in_lebenslauf": True})
    _make_md(tmp_path, "2 Beta", {"id": "2-beta", "titel": "Beta", "sichtbar_in_lebenslauf": False})
    (tmp_path / "ignored.txt").touch()

    # Pre-existing master YAML with non-project sections
    master_path = tmp_path / "workspace" / "bewerber" / "master_profile.yaml"
    master_path.write_text(yaml.safe_dump({
        "person": {"name": "Steve", "email": "s@x.de"},
        "berufsprofil": "kurz",
        "zielposition": ["KI Manager"],
    }, allow_unicode=True))

    n = sync_projects_into_profile()
    assert n == 2

    data = yaml.safe_load(master_path.read_text())
    assert data["person"]["name"] == "Steve"  # untouched
    ids = sorted(p["id"] for p in data["projekte"])
    assert ids == ["1-alpha", "2-beta"]
    alpha = next(p for p in data["projekte"] if p["id"] == "1-alpha")
    assert alpha["quelle"].endswith("1 Alpha/_profile.md")
    assert alpha["sichtbar_in_lebenslauf"] is True
    beta = next(p for p in data["projekte"] if p["id"] == "2-beta")
    assert beta["sichtbar_in_lebenslauf"] is False


def test_sync_creates_minimal_master_if_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path / "ws"))
    (tmp_path / "ws" / "bewerber").mkdir(parents=True)
    _make_md(tmp_path, "1 Alpha", {"id": "1-alpha", "titel": "Alpha", "sichtbar_in_lebenslauf": True})

    n = sync_projects_into_profile()
    assert n == 1

    master = tmp_path / "ws" / "bewerber" / "master_profile.yaml"
    data = yaml.safe_load(master.read_text())
    assert data["projekte"][0]["id"] == "1-alpha"
    assert data["person"]["name"] == "TODO Name"  # placeholder
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_sync.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/profile/sync.py`**

```python
import re
from pathlib import Path
import frontmatter
import yaml

from bewerber.shared.paths import Paths
from bewerber.shared.profile_schema import Project


SECTION_ORDER = [
    ("kurzbeschreibung", "Kurzbeschreibung"),
    ("rolle", "Meine Rolle / Beitrag"),
    ("skills_fachlich", "Fachliche Skills"),
    ("skills_methodisch", "Methodische Skills"),
    ("erfolge", "Erfolge / Outcomes"),
]


def parse_profile_md(path: Path) -> Project:
    """Parse `_profile.md` (front-matter + sectioned markdown) into a Project."""
    post = frontmatter.load(str(path))
    fields: dict[str, object] = {
        "id": post["id"],
        "titel": post["titel"],
        "sichtbar_in_lebenslauf": post.get("sichtbar_in_lebenslauf", True),
        "quelle": str(path),
    }

    sections = _split_sections(post.content)
    for key, heading in SECTION_ORDER:
        text = sections.get(heading, "").strip()
        if key in {"skills_fachlich", "skills_methodisch", "erfolge"}:
            items = _parse_bullets(text)
            fields[key] = items
        else:
            fields[key] = text

    return Project(**fields)


def _split_sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current is not None:
                out[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def _parse_bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if m:
            v = m.group(1).strip()
            if v and v != "(leer)":
                items.append(v)
    return items


def sync_projects_into_profile() -> int:
    """Read all `_profile.md` and merge into `projekte` section of master YAML."""
    paths = Paths()
    project_dicts: list[dict] = []

    for folder in paths.project_folders():
        md = folder / "_profile.md"
        if not md.is_file():
            continue
        project = parse_profile_md(md)
        project_dicts.append(project.model_dump(exclude_none=True))

    master_path = paths.master_profile
    if master_path.is_file():
        with master_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {
            "person": {"name": "TODO Name", "email": "todo@example.com"},
            "berufsprofil": "TODO: 2-3 Sätze über dich.",
            "zielposition": [],
            "ausbildung": [],
            "berufserfahrung": [],
            "zertifikate": [],
            "sprachen": [],
            "interessen": [],
        }

    data["projekte"] = project_dicts

    master_path.parent.mkdir(parents=True, exist_ok=True)
    with master_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    return len(project_dicts)
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_sync.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add bewerber/src/bewerber/profile/sync.py bewerber/tests/unit/test_sync.py
git commit -m "feat(profile): sync _profile.md into master_profile.yaml projekte section"
```

---

## Task 10: Wire `bewerber profile sync` Command

**Files:**
- Modify: `bewerber/src/bewerber/cli.py`
- Test: `bewerber/tests/unit/test_cli.py` (extend)

- [ ] **Step 1: Extend test**

Append to `bewerber/tests/unit/test_cli.py`:

```python
def test_profile_sync_calls_sync_function(mocker):
    fake_sync = mocker.patch("bewerber.cli.sync_projects_into_profile")
    fake_sync.return_value = 3
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "sync"])
    assert result.exit_code == 0, result.output
    assert "3" in result.output
    fake_sync.assert_called_once()
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_cli.py::test_profile_sync_calls_sync_function -v
```

Expected: AttributeError or test failure (sync_projects_into_profile not imported).

- [ ] **Step 3: Update `bewerber/src/bewerber/cli.py`**

Add import:

```python
from bewerber.profile.sync import sync_projects_into_profile
```

Replace `profile_sync`:

```python
@profile.command("sync")
def profile_sync() -> None:
    """Merged _profile.md aus Projektordnern in master_profile.yaml."""
    n = sync_projects_into_profile()
    paths = Paths()
    click.echo(f"{n} Projekte synchronisiert → {paths.master_profile}")
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add bewerber/src/bewerber/cli.py bewerber/tests/unit/test_cli.py
git commit -m "feat(cli): wire profile sync command"
```

---

## Task 11: Profile Extractor — Person, Education, Experience from Bewerbungsunterlagen

**Files:**
- Create: `bewerber/src/bewerber/profile/extractor.py`
- Test: `bewerber/tests/unit/test_extractor.py`

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_extractor.py`:

```python
from pathlib import Path
from bewerber.profile.extractor import (
    ExtractedProfile,
    extract_profile_from_documents,
)
from bewerber.shared.profile_schema import (
    Person,
    Ausbildung,
    Berufserfahrung,
    Zertifikat,
    Sprache,
)


def test_extract_profile_calls_llm_with_document_texts(tmp_path, mocker):
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    (docs_dir / "Lebenslauf.pdf").write_bytes(b"%PDF-1.4 fake")
    (docs_dir / "Zeugnis.pdf").write_bytes(b"%PDF-1.4 fake")

    mocker.patch(
        "bewerber.profile.extractor.read_document_text",
        side_effect=lambda p: f"text-of-{p.name}",
    )

    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ExtractedProfile(
        person=Person(name="Steve", email="s@x.de"),
        berufsprofil="kurz",
        zielposition=["KI Manager"],
        ausbildung=[Ausbildung(art="Techniker", institution="X")],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01", bis=None)
        ],
        zertifikate=[Zertifikat(name="REFA")],
        sprachen=[Sprache(sprache="Deutsch", niveau="Muttersprache")],
        interessen=["KI"],
    )

    profile = extract_profile_from_documents(docs_dir, llm=fake_llm)
    assert profile.person.name == "Steve"
    assert profile.berufserfahrung[0].firma == "Acme"

    args, kwargs = fake_llm.structured.call_args
    user_text = kwargs["user"]
    assert "Lebenslauf.pdf" in user_text
    assert "text-of-Lebenslauf.pdf" in user_text
    assert "text-of-Zeugnis.pdf" in user_text


def test_extract_skips_unsupported_files(tmp_path, mocker):
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    (docs_dir / "doc.pdf").write_bytes(b"x")
    (docs_dir / "ignored.jpg").write_bytes(b"x")
    (docs_dir / ".DS_Store").write_bytes(b"x")
    (docs_dir / "Bewerbungen").mkdir()
    (docs_dir / "Bewerbungen" / "alte.docx").write_bytes(b"x")  # subfolder excluded

    captured: list[str] = []
    mocker.patch(
        "bewerber.profile.extractor.read_document_text",
        side_effect=lambda p: (captured.append(p.name) or "x"),
    )
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ExtractedProfile(
        person=Person(name="X", email="x@y.de"),
        berufsprofil="k",
        zielposition=[],
        ausbildung=[],
        berufserfahrung=[],
        zertifikate=[],
        sprachen=[],
        interessen=[],
    )
    extract_profile_from_documents(docs_dir, llm=fake_llm)
    assert captured == ["doc.pdf"]
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_extractor.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/profile/extractor.py`**

```python
from pathlib import Path
from pydantic import BaseModel, Field

from bewerber.shared.document import read_document_text
from bewerber.shared.llm import LLMClient
from bewerber.shared.profile_schema import (
    Person,
    Ausbildung,
    Berufserfahrung,
    Zertifikat,
    Sprache,
)


SUPPORTED_EXT = {".pdf", ".docx"}

EXTRACTOR_SYSTEM_PROMPT = """Du extrahierst Lebenslauf-Daten aus deutschen Bewerbungsunterlagen (Zeugnisse, alte Lebensläufe).
Antworte ausschließlich auf Deutsch. Erfinde keine Daten.
Wenn ein Feld nicht in den Dokumenten enthalten ist, lass es leer oder als Liste leer.
Datumsformat für `von`/`bis`: YYYY-MM. Bei laufenden Anstellungen ist `bis` None.
`berufsprofil`: 2-3 Sätze, die den Bewerber zusammenfassen, basierend auf den Dokumenten.
`zielposition`: leer lassen — wird vom Nutzer manuell ergänzt."""


class ExtractedProfile(BaseModel):
    person: Person
    berufsprofil: str = Field(description="2-3 Sätze Zusammenfassung")
    zielposition: list[str] = Field(default_factory=list)
    ausbildung: list[Ausbildung] = Field(default_factory=list)
    berufserfahrung: list[Berufserfahrung] = Field(default_factory=list)
    zertifikate: list[Zertifikat] = Field(default_factory=list)
    sprachen: list[Sprache] = Field(default_factory=list)
    interessen: list[str] = Field(default_factory=list)


def collect_documents(docs_dir: Path) -> list[Path]:
    """Top-level supported documents in docs_dir (no subfolders)."""
    return sorted(
        f
        for f in docs_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
    )


def extract_profile_from_documents(
    docs_dir: Path, llm: LLMClient
) -> ExtractedProfile:
    """Read PDFs/DOCX in docs_dir, send concatenated text to LLM, return structured profile."""
    files = collect_documents(docs_dir)
    if not files:
        raise FileNotFoundError(f"Keine PDF/DOCX-Dateien in {docs_dir}")

    parts: list[str] = []
    for f in files:
        try:
            text = read_document_text(f)
        except Exception as e:  # noqa: BLE001
            text = f"<Lesefehler: {e}>"
        parts.append(f"\n--- {f.name} ---\n{text}\n")

    user = (
        "Folgende Bewerbungsunterlagen liegen vor. "
        "Extrahiere ein strukturiertes Lebenslauf-Profil daraus.\n"
        + "".join(parts)
    )
    return llm.structured(
        system=EXTRACTOR_SYSTEM_PROMPT,
        user=user,
        schema=ExtractedProfile,
    )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_extractor.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add bewerber/src/bewerber/profile/extractor.py bewerber/tests/unit/test_extractor.py
git commit -m "feat(profile): LLM extractor for person/education/experience from documents"
```

---

## Task 12: Anschreiben Examples Selection (Few-Shot Source)

**Files:**
- Modify: `bewerber/src/bewerber/profile/extractor.py`
- Test: extend `bewerber/tests/unit/test_extractor.py`

- [ ] **Step 1: Append test**

Append to `bewerber/tests/unit/test_extractor.py`:

```python
from bewerber.profile.extractor import save_anschreiben_examples


def test_save_anschreiben_examples_writes_text_files(tmp_path, mocker):
    src1 = tmp_path / "Anschreiben_A.docx"
    src2 = tmp_path / "Anschreiben_B.pdf"
    src1.write_bytes(b"x")
    src2.write_bytes(b"x")

    mocker.patch(
        "bewerber.profile.extractor.read_document_text",
        side_effect=lambda p: f"INHALT VON {p.name}",
    )

    out_dir = tmp_path / "examples"
    saved = save_anschreiben_examples([src1, src2], out_dir)
    assert len(saved) == 2
    assert saved[0].suffix == ".txt"
    assert saved[0].read_text(encoding="utf-8") == "INHALT VON Anschreiben_A.docx"
    assert saved[1].read_text(encoding="utf-8") == "INHALT VON Anschreiben_B.pdf"


def test_save_anschreiben_examples_creates_dir(tmp_path, mocker):
    src = tmp_path / "X.docx"
    src.write_bytes(b"x")
    mocker.patch("bewerber.profile.extractor.read_document_text", return_value="text")
    out_dir = tmp_path / "deep" / "nested" / "examples"
    saved = save_anschreiben_examples([src], out_dir)
    assert out_dir.is_dir()
    assert saved[0].parent == out_dir
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_extractor.py -v
```

Expected: 2 new tests fail (function not defined).

- [ ] **Step 3: Append to `bewerber/src/bewerber/profile/extractor.py`**

```python
def save_anschreiben_examples(
    sources: list[Path], out_dir: Path
) -> list[Path]:
    """Read each source as text, save to out_dir as `NN_<stem>.txt`. Returns saved paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for i, src in enumerate(sources, start=1):
        text = read_document_text(src)
        out = out_dir / f"{i:02d}_{src.stem}.txt"
        out.write_text(text, encoding="utf-8")
        saved.append(out)
    return saved
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_extractor.py -v
```

Expected: 4 passed (2 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add bewerber/src/bewerber/profile/extractor.py bewerber/tests/unit/test_extractor.py
git commit -m "feat(profile): save_anschreiben_examples utility for few-shot source"
```

---

## Task 13: Wire `bewerber profile init` Command

**Files:**
- Modify: `bewerber/src/bewerber/cli.py`
- Test: `bewerber/tests/unit/test_cli.py` (extend)

This command is interactive: extract → user picks anschreiben examples → save → write master YAML. Confirms before overwriting existing master.

- [ ] **Step 1: Extend test**

Append to `bewerber/tests/unit/test_cli.py`:

```python
import yaml
from bewerber.shared.profile_schema import Person
from bewerber.profile.extractor import ExtractedProfile


def test_profile_init_writes_master_yaml(tmp_path, monkeypatch, mocker):
    bewerb_dir = tmp_path / "bewerber"
    bewerb_dir.mkdir(parents=True)
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    (docs_dir / "Lebenslauf.pdf").write_bytes(b"x")
    (docs_dir / "Bewerbungen").mkdir()
    (docs_dir / "Bewerbungen" / "Steve_KI.docx").write_bytes(b"x")

    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    monkeypatch.setattr(
        "bewerber.cli.extract_profile_from_documents",
        lambda d, llm: ExtractedProfile(
            person=Person(name="Steve", email="s@x.de"),
            berufsprofil="profil",
            zielposition=[],
            ausbildung=[],
            berufserfahrung=[],
            zertifikate=[],
            sprachen=[],
            interessen=[],
        ),
    )
    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)
    monkeypatch.setattr(
        "bewerber.cli.save_anschreiben_examples",
        lambda srcs, out: [out / "01_x.txt"],
    )

    runner = CliRunner()
    # answer "no" to interactive anschreiben selection prompt → empty list
    result = runner.invoke(main, ["profile", "init"], input="\n")
    assert result.exit_code == 0, result.output

    master = bewerb_dir / "master_profile.yaml"
    assert master.exists()
    data = yaml.safe_load(master.read_text())
    assert data["person"]["name"] == "Steve"


def test_profile_init_aborts_if_master_exists_and_no_force(tmp_path, monkeypatch):
    bewerb_dir = tmp_path / "bewerber"
    bewerb_dir.mkdir(parents=True)
    (bewerb_dir / "master_profile.yaml").write_text("person: {name: existing}")
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    (docs_dir / "x.pdf").write_bytes(b"x")

    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(main, ["profile", "init"])
    assert result.exit_code != 0
    assert "existiert" in result.output.lower() or "force" in result.output.lower()
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 2 new tests fail.

- [ ] **Step 3: Update `bewerber/src/bewerber/cli.py`**

Add imports near the top:

```python
import yaml
from bewerber.profile.extractor import (
    extract_profile_from_documents,
    save_anschreiben_examples,
)
```

Replace `profile_init`:

```python
@profile.command("init")
@click.option("--force", is_flag=True, help="Überschreibt existierende master_profile.yaml")
def profile_init(force: bool) -> None:
    """Erzeugt master_profile.yaml aus Bewerbungsunterlagen/."""
    paths = Paths()
    if paths.master_profile.exists() and not force:
        click.echo(
            f"master_profile.yaml existiert bereits in {paths.bewerber_dir}. "
            "Mit --force überschreiben."
        )
        raise click.exceptions.Exit(1)

    if not paths.bewerbungsunterlagen.is_dir():
        click.echo(f"Bewerbungsunterlagen nicht gefunden: {paths.bewerbungsunterlagen}")
        raise click.exceptions.Exit(1)

    llm = LLMClient()
    click.echo(f"Lese Dokumente aus {paths.bewerbungsunterlagen} …")
    profile = extract_profile_from_documents(paths.bewerbungsunterlagen, llm=llm)
    click.echo(f"Extrahiert: {profile.person.name}, {len(profile.berufserfahrung)} Stellen")

    bewerbungen = paths.bewerbungen
    selected: list = []
    if bewerbungen.is_dir():
        candidates = sorted(
            f for f in bewerbungen.iterdir()
            if f.is_file() and f.suffix.lower() in {".pdf", ".docx"}
        )
        if candidates:
            click.echo("\nVerfügbare bisherige Bewerbungen für Stil-Few-Shots:")
            for i, f in enumerate(candidates, start=1):
                click.echo(f"  [{i:>2}] {f.name}")
            answer = click.prompt(
                "Welche als Stil-Beispiele speichern? (Nummern komma-separiert, leer = keine)",
                default="",
                show_default=False,
            )
            if answer.strip():
                indices = [int(x) for x in answer.split(",") if x.strip().isdigit()]
                selected = [candidates[i - 1] for i in indices if 1 <= i <= len(candidates)]

    if selected:
        saved = save_anschreiben_examples(selected, paths.anschreiben_examples)
        click.echo(f"{len(saved)} Anschreiben-Beispiele gespeichert in {paths.anschreiben_examples}")

    paths.bewerber_dir.mkdir(parents=True, exist_ok=True)
    data = profile.model_dump(exclude_none=True)
    data["projekte"] = []  # populated by `profile sync` later
    with paths.master_profile.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    click.echo(f"\n✔ master_profile.yaml geschrieben: {paths.master_profile}")
    click.echo("Nächster Schritt: `bewerber projects scan` und `bewerber profile sync`.")
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 8 passed (all CLI tests).

- [ ] **Step 5: Commit**

```bash
git add bewerber/src/bewerber/cli.py bewerber/tests/unit/test_cli.py
git commit -m "feat(cli): wire profile init command (interactive, with anschreiben selection)"
```

---

## Task 14: Integration Test — End-to-End Profile Build

**Files:**
- Create: `bewerber/tests/integration/__init__.py` (empty)
- Create: `bewerber/tests/integration/test_e2e_profile.py`

End-to-end smoke test that exercises all three commands against a fully-mocked LLM, verifying the master YAML is valid against the schema.

- [ ] **Step 1: Write integration test**

Write to `bewerber/tests/integration/test_e2e_profile.py`:

```python
import yaml
from pathlib import Path
from click.testing import CliRunner

from bewerber.cli import main
from bewerber.shared.profile_schema import (
    MasterProfile,
    Person,
    Ausbildung,
    Berufserfahrung,
    Zertifikat,
    Sprache,
)
from bewerber.profile.extractor import ExtractedProfile
from bewerber.profile.projects import ProjectDraft


def test_full_profile_workflow(tmp_path, monkeypatch, mocker):
    # Layout
    workspace = tmp_path / "Bewerber_Assistent"
    documents = tmp_path
    (workspace / "bewerber").mkdir(parents=True)
    bu = documents / "Bewerbungsunterlagen"
    bu.mkdir()
    (bu / "Lebenslauf.pdf").write_bytes(b"x")
    bu_bewerbungen = bu / "Bewerbungen"
    bu_bewerbungen.mkdir()

    p1 = documents / "1 Kleinanzeigen"
    p1.mkdir()
    (p1 / "README.md").write_text("# Kleinanzeigen\nMarketplace bot.")
    p2 = documents / "8 n8n_builder"
    p2.mkdir()
    (p2 / "README.md").write_text("# n8n Builder\nWorkflow tool.")

    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(documents))

    # Mock LLM at extractor + project layer
    monkeypatch.setattr(
        "bewerber.cli.extract_profile_from_documents",
        lambda d, llm: ExtractedProfile(
            person=Person(name="Steve", email="s@x.de"),
            berufsprofil="profil",
            zielposition=["KI Manager"],
            ausbildung=[Ausbildung(art="Techniker", institution="X")],
            berufserfahrung=[
                Berufserfahrung(position="PM", firma="Acme", von="2020-01", bis=None)
            ],
            zertifikate=[Zertifikat(name="REFA")],
            sprachen=[Sprache(sprache="Deutsch", niveau="Muttersprache")],
            interessen=[],
        ),
    )
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ProjectDraft(
        kurzbeschreibung="Beschreibung.",
        rolle="Entwickler.",
        skills_fachlich=["Python"],
        skills_methodisch=["Agile"],
        erfolge=[],
    )
    monkeypatch.setattr("bewerber.cli.LLMClient", lambda: fake_llm)

    runner = CliRunner()

    # 1. profile init (no anschreiben selected)
    result = runner.invoke(main, ["profile", "init"], input="\n")
    assert result.exit_code == 0, result.output

    # 2. projects scan
    result = runner.invoke(main, ["projects", "scan"])
    assert result.exit_code == 0, result.output
    assert (p1 / "_profile.md").is_file()
    assert (p2 / "_profile.md").is_file()

    # 3. profile sync
    result = runner.invoke(main, ["profile", "sync"])
    assert result.exit_code == 0, result.output
    assert "2" in result.output

    # Validate the resulting master YAML
    master = workspace / "bewerber" / "master_profile.yaml"
    data = yaml.safe_load(master.read_text())
    profile = MasterProfile(**data)
    assert profile.person.name == "Steve"
    assert len(profile.projekte) == 2
    project_ids = sorted(p.id for p in profile.projekte)
    assert project_ids == ["1-kleinanzeigen", "8-n8n-builder"]
    assert profile.berufserfahrung[0].firma == "Acme"
```

- [ ] **Step 2: Run integration test**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
pytest tests/integration/ -v
```

Expected: 1 passed.

- [ ] **Step 3: Run full suite**

```bash
pytest -v
```

Expected: all tests pass (~25-30 tests).

- [ ] **Step 4: Commit**

```bash
git add bewerber/tests/integration/
git commit -m "test(profile): end-to-end workflow integration test"
```

---

## Task 15: Run Real Workflow Against Steve's Data (Smoke)

This is the user-facing acceptance step. Run the actual commands against the real Bewerbungsunterlagen + project folders. **Requires real OpenAI API key.**

- [ ] **Step 1: Verify `.env` has API key**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
test -f .env && grep -q "^OPENAI_API_KEY=sk-" .env && echo "ok" || echo "missing — run: cp .env.example .env && edit .env"
```

Expected: "ok". If missing: copy and edit.

- [ ] **Step 2: Run `profile init`**

```bash
source .venv/bin/activate
bewerber profile init
```

Expected: Command lists Bewerbungsunterlagen contents, extracts profile via LLM, prompts for anschreiben selection, writes `master_profile.yaml`. Manual verification: open `master_profile.yaml`, check person/ausbildung/berufserfahrung look correct. Edit if needed.

- [ ] **Step 3: Run `projects scan`**

```bash
bewerber projects scan
```

Expected: Iterates ~17 folders, generates `_profile.md` in each. Spot-check 2–3 of them — verify content is reasonable.

- [ ] **Step 4: Manually edit a few `_profile.md`**

Open 2–3 `_profile.md` files in your editor. Verify or correct:
- Kurzbeschreibung
- Meine Rolle
- Skills (fachlich/methodisch)

This is the "Hybrid" workflow from the spec — LLM draft + your refinement.

- [ ] **Step 5: Run `profile sync`**

```bash
bewerber profile sync
```

Expected: "N Projekte synchronisiert". Open `master_profile.yaml`, verify `projekte:` section has all entries with your edits intact.

- [ ] **Step 6: Validate against schema**

```bash
python3 -c "
import yaml
from bewerber.shared.profile_schema import MasterProfile
data = yaml.safe_load(open('master_profile.yaml').read())
p = MasterProfile(**data)
print(f'OK — {len(p.projekte)} Projekte, {len(p.berufserfahrung)} Stellen, {len(p.ausbildung)} Ausbildungen')
"
```

Expected: prints "OK — N Projekte, M Stellen, K Ausbildungen" without ValidationError.

- [ ] **Step 7: Commit final state of profile (gitignored, but document run)**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git log --oneline | head -20
```

Document run in a brief note at `bewerber/RUNLOG.md`:

```markdown
# Run Log

## 2026-05-05 — Plan A initial profile build
- `profile init` extracted: <person.name>, <N> Stellen, <M> Ausbildungen
- `projects scan` generated `_profile.md` in <N> folders
- Manually edited: <list folders you edited>
- `profile sync`: <N> Projekte synced
- Master YAML validates against schema ✔
```

```bash
git add bewerber/RUNLOG.md
git commit -m "docs: initial profile build run log"
```

---

## Self-Review

**Spec coverage check (Subsystem 1: Profil-Aufbau):**

| Spec requirement | Task |
|------------------|------|
| `bewerber profile init` reads PDFs | Task 11, 13 |
| Extracts person/ausbildung/berufserfahrung | Task 11, 13 |
| Anschreiben examples to `anschreiben_examples/` | Task 12, 13 |
| `bewerber projects scan` iterates project folders | Task 7, 8 |
| `_profile.md` per folder with front-matter + sections | Task 7 |
| Idempotent (skips existing without `--force`) | Task 7 |
| LLM reads README/code/dotfiles, sampling at 30k tokens | Task 7 |
| `bewerber profile sync` merges markdown into YAML | Task 9, 10 |
| Verlustfrei: other YAML sections untouched | Task 9 |
| Pydantic schema validates master YAML | Task 2, 14 |
| Path constants central, env-var overridable | Task 3 |
| LLM wrapper with structured outputs | Task 4 |
| Document reader for PDF + DOCX | Task 5 |
| CLI Click groups: profile, projects | Task 6, 8, 10, 13 |

All Subsystem-1 spec items covered ✔

**Placeholder scan:** searched for "TBD", "TODO" in code. The only TODO is the placeholder `"TODO Name"` / `"todo@example.com"` in `sync.py` when no master YAML exists yet — this is intentional and tested. None elsewhere.

**Type consistency:** `ExtractedProfile`, `ProjectDraft`, `MasterProfile`, `Project` types match across tasks. CLI imports match function signatures. `LLMClient.structured(*, system, user, schema)` is consistent across all callers (extractor, projects).

**One ambiguity caught and fixed:** Task 13's `profile init` doesn't ask whether to overwrite — it errors out without `--force`. The corresponding test verifies this. Behavior matches Idempotenz principle from spec.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-05-plan-a-foundation-profile.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
