# Plan C — Tailoring Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Tailoring subsystem of the Bewerber-Assistent: given a job posting (URL or file), generate a tailored deutscher Lebenslauf PDF + Anschreiben PDF based on `master_profile.yaml`, snapshot the posting for archival, and save everything in a dated Bewerbungsordner.

**Architecture:** Three LLM-driven stages compose a pipeline: (1) ingest posting (Playwright for URL, document reader for file), (2) LLM customizes Lebenslauf from Master-Profil and writes deutsches Anschreiben (with optional few-shot examples), (3) WeasyPrint renders Jinja2 HTML templates to PDF. Output stored at `Bewerbungsunterlagen/Bewerbungen/<datum>_<firma>_<rolle>/` with audit log. Stage isolation: HTML/Markdown sources stay editable; `--rebuild` regenerates PDFs only without LLM cost.

**Tech Stack:** Python 3.11+, Click, WeasyPrint (HTML+CSS → PDF, deutsche Umlaute OK), Jinja2 (templates), Playwright (URL snapshot + meta-extraction), markdown-it-py (Markdown → HTML), pydantic v2 (LLM schemas), OpenAI structured outputs (gpt-5.1-mini).

**Spec reference:** [docs/superpowers/specs/2026-05-04-bewerber-assistent-design.md](../specs/2026-05-04-bewerber-assistent-design.md), Subsystem 3 (Tailoring).

**Prerequisites:** Plan A complete. `master_profile.yaml` exists and validates against schema. `bewerber profile init / projects scan / profile sync` all work. Optional: `anschreiben_examples/*.txt` exist (improves Anschreiben quality).

---

## File Structure (Plan C)

```
/Users/steve/Documents/Bewerber_Assistent/
└── bewerber/
    ├── pyproject.toml                         # +deps: weasyprint, playwright, markdown-it-py, python-slugify
    ├── src/bewerber/
    │   ├── cli.py                             # +tailor command
    │   ├── shared/
    │   │   └── slug.py                        # filesystem-safe slugification (umlauts → ascii)
    │   └── tailoring/                         # new package
    │       ├── __init__.py
    │       ├── posting.py                     # JobPosting model, read from URL or file
    │       ├── snapshot.py                    # Playwright snapshot (HTML + PDF + meta)
    │       ├── customize.py                   # LLM pass: filter/reorder Lebenslauf
    │       ├── anschreiben.py                 # LLM pass: write Anschreiben
    │       ├── render.py                      # WeasyPrint render Lebenslauf + Anschreiben PDFs
    │       └── orchestrator.py                # end-to-end tailor function
    ├── templates/                             # NEW: Jinja2 templates
    │   ├── lebenslauf.html.j2
    │   └── anschreiben.html.j2
    └── tests/
        ├── unit/
        │   ├── test_slug.py
        │   ├── test_posting.py
        │   ├── test_customize.py
        │   ├── test_anschreiben.py
        │   ├── test_render.py
        │   └── test_orchestrator.py
        ├── integration/
        │   └── test_tailor_e2e.py
        └── fixtures/
            ├── sample_posting.html
            ├── sample_posting.txt
            └── tailor_master_profile.yaml
```

**Module responsibilities:**
- `posting.py`: pure data — read job text from any source, return a `JobPosting` dataclass. No LLM.
- `snapshot.py`: side-effects — Playwright opens URL, writes `posting.html` + `posting.pdf` + extracts kontakt via LLM.
- `customize.py`: LLM pass 1 — input = Master-Profil + Job-Description → output = filtered/reordered `CustomizedResume`.
- `anschreiben.py`: LLM pass 2 — input = Master-Profil + Job + scoring hints + few-shot examples → output = Markdown.
- `render.py`: WeasyPrint + Jinja2 — pure rendering, no LLM.
- `orchestrator.py`: pipeline composition.
- `slug.py`: `("BMW Group", "KI Manager (m/w/d)")` → `"BMW-Group_KI-Manager"` (ascii-fold, single source of truth for filesystem naming).

---

## Task 1: Add Plan C Dependencies

**Files:**
- Modify: `bewerber/pyproject.toml`

- [ ] **Step 1: Update pyproject.toml dependencies**

Read the current `bewerber/pyproject.toml`. Find the `dependencies = [...]` list under `[project]`. Replace with the same list plus these four new entries appended:

```toml
    "weasyprint>=62.0",
    "playwright>=1.40",
    "markdown-it-py>=3.0",
    "python-slugify>=8.0",
```

The full block should now be:

```toml
dependencies = [
    "click>=8.1",
    "pydantic>=2.5",
    "email-validator>=2.0",
    "pyyaml>=6.0",
    "python-frontmatter>=1.0",
    "pdfplumber>=0.10",
    "python-docx>=1.1",
    "openai>=1.40",
    "python-dotenv>=1.0",
    "weasyprint>=62.0",
    "playwright>=1.40",
    "markdown-it-py>=3.0",
    "python-slugify>=8.0",
]
```

- [ ] **Step 2: Install new deps**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: "Successfully installed weasyprint-... playwright-... markdown-it-py-... python-slugify-..."

- [ ] **Step 3: Install Playwright browser**

```bash
playwright install chromium
```

Expected: Downloads chromium binary (~150MB, one-time). Final line: "Playwright Host validation warning" is OK; the install succeeds.

- [ ] **Step 4: Verify WeasyPrint works (it depends on system libs like pango on macOS)**

```bash
python3 -c "from weasyprint import HTML; print(HTML(string='<h1>ok</h1>').write_pdf()[:4])"
```

Expected: `b'%PDF'` (the first 4 bytes of a valid PDF). If this fails with a library error, run `brew install pango` on macOS, then re-test.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/pyproject.toml
git commit -m "chore(deps): add tailoring deps (weasyprint, playwright, markdown-it, slugify)"
```

---

## Task 2: Filesystem-Safe Slugification

**Files:**
- Create: `bewerber/src/bewerber/shared/slug.py`
- Test: `bewerber/tests/unit/test_slug.py`

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_slug.py`:

```python
from bewerber.shared.slug import slug_part, bewerbungsordner_name


def test_slug_part_handles_umlauts():
    assert slug_part("Müller GmbH") == "Mueller-GmbH"
    assert slug_part("Bäcker & Söhne") == "Baecker-Soehne"


def test_slug_part_handles_special_chars():
    assert slug_part("KI Manager (m/w/d)") == "KI-Manager-m-w-d"
    assert slug_part("C++") == "C"  # special chars dropped


def test_slug_part_collapses_dashes():
    assert slug_part("A    B---C") == "A-B-C"


def test_slug_part_preserves_case():
    """Firma names like BMW, SAP should not become bmw, sap."""
    assert slug_part("BMW Group") == "BMW-Group"


def test_slug_part_strips_leading_trailing_dashes():
    assert slug_part("---hello---") == "hello"


def test_bewerbungsordner_name():
    name = bewerbungsordner_name("2026-06-12", "BMW Group", "KI Manager (m/w/d)")
    assert name == "2026-06-12_BMW-Group_KI-Manager-m-w-d"


def test_bewerbungsordner_name_empty_role():
    name = bewerbungsordner_name("2026-06-12", "Acme", "")
    assert name == "2026-06-12_Acme"
```

- [ ] **Step 2: Run, verify fail**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
pytest tests/unit/test_slug.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/shared/slug.py`**

```python
import re


UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss",
})


def slug_part(text: str) -> str:
    """Filesystem-safe slug preserving case. Empty input → empty string.

    Umlauts are transliterated (ä→ae). Non-alphanumeric becomes `-`. Multiple
    dashes collapse. Leading/trailing dashes stripped.
    """
    if not text:
        return ""
    transliterated = text.translate(UMLAUT_MAP)
    with_dashes = re.sub(r"[^A-Za-z0-9]+", "-", transliterated)
    collapsed = re.sub(r"-+", "-", with_dashes)
    return collapsed.strip("-")


def bewerbungsordner_name(date_str: str, firma: str, rolle: str) -> str:
    """Build folder name: `YYYY-MM-DD_Firma-Slug_Rolle-Slug`. Rolle optional."""
    firma_s = slug_part(firma)
    rolle_s = slug_part(rolle)
    parts = [date_str, firma_s]
    if rolle_s:
        parts.append(rolle_s)
    return "_".join(parts)
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_slug.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/shared/slug.py bewerber/tests/unit/test_slug.py
git commit -m "feat(shared): filesystem-safe slug for Bewerbungsordner naming"
```

---

## Task 3: JobPosting Data Model + File Reader

**Files:**
- Create: `bewerber/src/bewerber/tailoring/__init__.py` (empty)
- Create: `bewerber/src/bewerber/tailoring/posting.py`
- Test: `bewerber/tests/unit/test_posting.py`
- Test fixture: `bewerber/tests/fixtures/sample_posting.txt`

- [ ] **Step 1: Create the fixture**

```bash
mkdir -p /Users/steve/Documents/Bewerber_Assistent/bewerber/tests/fixtures
cat > /Users/steve/Documents/Bewerber_Assistent/bewerber/tests/fixtures/sample_posting.txt << 'EOF'
KI Produktmanager (m/w/d)
BMW Group, München

Wir suchen einen erfahrenen KI Produktmanager zur Leitung unserer KI-Initiativen
im Bereich autonomes Fahren. Sie verantworten die Roadmap, arbeiten mit
Data-Science-Teams und stakeholdern aus Engineering, Produkt und Marketing.

Anforderungen:
- 5+ Jahre Erfahrung in Produktmanagement
- Erfahrung mit KI/ML-Produkten
- Sehr gute Deutsch- und Englischkenntnisse
- Tools: Jira, Confluence, Python (Grundlagen)

Kontakt: Frau Anna Müller, anna.mueller@bmw.de
EOF
```

- [ ] **Step 2: Write failing test**

Write to `bewerber/tests/unit/test_posting.py`:

```python
from pathlib import Path
from bewerber.tailoring.posting import JobPosting, read_posting_from_file


def test_jobposting_dataclass():
    p = JobPosting(
        title="KI Manager",
        firma="BMW",
        location="München",
        description="text",
        source_url=None,
        kontakt_name=None,
        kontakt_email=None,
    )
    assert p.title == "KI Manager"
    assert p.firma == "BMW"
    assert p.kontakt_email is None


def test_read_posting_from_txt(fixtures_dir: Path):
    p = read_posting_from_file(fixtures_dir / "sample_posting.txt")
    assert p.source_url is None
    assert "KI Produktmanager" in p.description
    assert "BMW Group" in p.description
    # title/firma/location not auto-parsed from raw text — kept None
    assert p.title is None or "KI" in (p.title or "")


def test_read_posting_from_pdf(fixtures_dir: Path):
    """PDF support reuses shared/document.py."""
    p = read_posting_from_file(fixtures_dir / "sample_resume.pdf")
    assert p.description  # non-empty


def test_read_posting_unsupported_format(tmp_path):
    f = tmp_path / "x.xyz"
    f.write_text("nope")
    try:
        read_posting_from_file(f)
    except ValueError as e:
        assert "unsupported" in str(e).lower() or "xyz" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 3: Run, verify fail**

```bash
pytest tests/unit/test_posting.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `bewerber/src/bewerber/tailoring/__init__.py`** (empty file).

- [ ] **Step 5: Implement `bewerber/src/bewerber/tailoring/posting.py`**

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bewerber.shared.document import read_document_text


@dataclass
class JobPosting:
    """Structured representation of a job posting.

    Free-text fields (title, firma, location, kontakt) may be None when the
    source is unstructured plain text. The LLM customize stage populates
    them via posting_meta.yaml if needed.
    """
    title: Optional[str]
    firma: Optional[str]
    location: Optional[str]
    description: str
    source_url: Optional[str]
    kontakt_name: Optional[str]
    kontakt_email: Optional[str]


def read_posting_from_file(path: Path) -> JobPosting:
    """Read posting from .txt / .pdf / .docx. Returns JobPosting with description only."""
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".txt":
        text = path.read_text(encoding="utf-8")
    elif suffix in {".pdf", ".docx"}:
        text = read_document_text(path)
    else:
        raise ValueError(f"Unsupported posting format: {suffix}")

    return JobPosting(
        title=None,
        firma=None,
        location=None,
        description=text,
        source_url=None,
        kontakt_name=None,
        kontakt_email=None,
    )
```

- [ ] **Step 6: Run, verify pass**

```bash
pytest tests/unit/test_posting.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/tailoring/ bewerber/tests/unit/test_posting.py bewerber/tests/fixtures/sample_posting.txt
git commit -m "feat(tailoring): JobPosting model and file reader (txt/pdf/docx)"
```

---

## Task 4: Posting Snapshot via Playwright (URL → HTML + PDF)

**Files:**
- Create: `bewerber/src/bewerber/tailoring/snapshot.py`
- Test: `bewerber/tests/unit/test_snapshot.py`

This task isolates the Playwright code so it can be mocked in tests. We test the *interface* (correct calls to Playwright APIs), not the actual browser behavior.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_snapshot.py`:

```python
from pathlib import Path
from bewerber.tailoring.snapshot import snapshot_url, _extract_text_from_html


def test_extract_text_strips_html_tags():
    html = "<html><body><h1>KI Manager</h1><p>Sie&nbsp;leiten...</p><script>x()</script></body></html>"
    text = _extract_text_from_html(html)
    assert "KI Manager" in text
    assert "Sie leiten" in text  # nbsp → space
    assert "<script>" not in text  # tags stripped
    assert "x()" not in text  # script content removed


def test_snapshot_url_writes_html_and_pdf(tmp_path, mocker):
    """Snapshot writes posting.html and posting.pdf via mocked Playwright."""

    # Mock the playwright sync_playwright context manager
    fake_page = mocker.Mock()
    fake_page.content.return_value = "<html><body><h1>KI Manager</h1><p>Beschreibung</p></body></html>"
    fake_page.pdf.return_value = b"%PDF-fake"

    fake_browser = mocker.Mock()
    fake_browser.new_page.return_value = fake_page
    fake_browser.close = mocker.Mock()

    fake_pw = mocker.Mock()
    fake_pw.chromium.launch.return_value = fake_browser

    fake_ctx = mocker.MagicMock()
    fake_ctx.__enter__.return_value = fake_pw
    fake_ctx.__exit__.return_value = False

    mocker.patch("bewerber.tailoring.snapshot.sync_playwright", return_value=fake_ctx)

    out_dir = tmp_path / "snap"
    text = snapshot_url("https://example.com/job/123", out_dir)

    assert (out_dir / "posting.html").is_file()
    assert (out_dir / "posting.pdf").is_file()
    assert (out_dir / "posting.html").read_text(encoding="utf-8").startswith("<html>")
    assert (out_dir / "posting.pdf").read_bytes().startswith(b"%PDF")
    assert "KI Manager" in text
    assert "Beschreibung" in text
    fake_page.goto.assert_called_once_with("https://example.com/job/123", wait_until="domcontentloaded", timeout=30000)
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_snapshot.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/tailoring/snapshot.py`**

```python
import re
from pathlib import Path
from playwright.sync_api import sync_playwright


def snapshot_url(url: str, out_dir: Path) -> str:
    """Open URL with headless Chromium, save HTML and printable PDF.

    Returns the extracted plain text (no HTML tags) for downstream LLM use.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            pdf_bytes = page.pdf(format="A4", margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"})
        finally:
            browser.close()

    (out_dir / "posting.html").write_text(html, encoding="utf-8")
    (out_dir / "posting.pdf").write_bytes(pdf_bytes)
    return _extract_text_from_html(html)


def _extract_text_from_html(html: str) -> str:
    """Strip tags + scripts + styles, decode nbsp/entities to plain text."""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_snapshot.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/tailoring/snapshot.py bewerber/tests/unit/test_snapshot.py
git commit -m "feat(tailoring): Playwright snapshot writes posting.html + posting.pdf"
```

---

## Task 5: LLM Customize Lebenslauf

**Files:**
- Create: `bewerber/src/bewerber/tailoring/customize.py`
- Test: `bewerber/tests/unit/test_customize.py`

LLM pass 1: given Master-Profil + Job-Description, decide what to emphasize. Returns a `CustomizedResume` with selected/reordered Berufserfahrung, projekte, and zugespitzte bullets.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_customize.py`:

```python
from bewerber.tailoring.customize import (
    CustomizedResume,
    CustomBerufserfahrung,
    CustomProject,
    customize_resume,
)
from bewerber.shared.profile_schema import MasterProfile, Person, Berufserfahrung, Project


def _master() -> MasterProfile:
    return MasterProfile(
        person=Person(name="Steve", email="s@x.de"),
        berufsprofil="Erfahrener Manager.",
        zielposition=["KI Manager"],
        ausbildung=[],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01", bis="2024-08",
                            aufgaben=["a1", "a2"], erfolge=["e1"], skills=["s1"]),
            Berufserfahrung(position="Engineer", firma="Old", von="2015-01", bis="2019-12",
                            aufgaben=["o1"], erfolge=[], skills=["s2"]),
        ],
        projekte=[
            Project(id="1-x", titel="X", kurzbeschreibung="kb", rolle="r",
                    skills_fachlich=["Python"], sichtbar_in_lebenslauf=True),
            Project(id="2-y", titel="Y", kurzbeschreibung="hidden", rolle="r",
                    skills_fachlich=["X"], sichtbar_in_lebenslauf=False),
        ],
    )


def test_customize_calls_llm_with_master_and_job(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = CustomizedResume(
        berufsprofil_zugespitzt="Tailored profil.",
        berufserfahrung=[
            CustomBerufserfahrung(position="PM", firma="Acme", von="2020-01", bis="2024-08",
                                   aufgaben=["a1 (geschärft)", "a2"], erfolge=["e1"], skills=["s1"]),
        ],
        projekte_hervorheben=["1-x"],
        skills_reihenfolge=["s1", "Python"],
    )
    profile = _master()
    job_text = "KI Manager bei BMW. Python und Projekterfahrung gesucht."

    result = customize_resume(profile, job_text, llm=fake_llm)
    assert result.berufsprofil_zugespitzt.startswith("Tailored")
    assert result.projekte_hervorheben == ["1-x"]

    args, kwargs = fake_llm.structured.call_args
    user_prompt = kwargs["user"]
    assert "KI Manager bei BMW" in user_prompt
    assert "Acme" in user_prompt  # master content in prompt
    assert kwargs["schema"] is CustomizedResume


def test_customize_filters_hidden_projects_from_prompt(mocker):
    """sichtbar_in_lebenslauf=False projects must not appear in the LLM prompt."""
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = CustomizedResume(
        berufsprofil_zugespitzt="X.",
        berufserfahrung=[],
        projekte_hervorheben=[],
        skills_reihenfolge=[],
    )
    profile = _master()
    customize_resume(profile, "job text", llm=fake_llm)
    user_prompt = fake_llm.structured.call_args.kwargs["user"]
    assert "1-x" in user_prompt  # visible
    assert "hidden" not in user_prompt  # hidden project not in prompt
    assert "2-y" not in user_prompt
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_customize.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/tailoring/customize.py`**

```python
from typing import Optional
import yaml
from pydantic import BaseModel, Field, ConfigDict

from bewerber.shared.llm import LLMClient
from bewerber.shared.profile_schema import MasterProfile


CUSTOMIZE_SYSTEM_PROMPT = """Du bist ein erfahrener deutscher Karriere-Coach. Du passt einen vorhandenen Lebenslauf
für eine spezifische Stellenausschreibung an.

KRITISCHE REGELN:
1. Erfinde KEINE Inhalte. Du darfst NUR aus den gegebenen Master-Profil-Daten zitieren oder umformulieren.
2. Wenn ein gefordertes Skill nicht im Master vorhanden ist, lass es weg — füge es nicht hinzu.
3. Du darfst Bullet-Points umformulieren, um Sprache auf die Ausschreibung auszurichten — Inhalt muss aber im Master stehen.
4. Antworte ausschließlich auf Deutsch.
5. Datumsangaben bleiben unverändert (YYYY-MM Format).

Deine Aufgabe:
- `berufsprofil_zugespitzt`: 2-3 Sätze, neu formuliert, um Match zur Ausschreibung herzustellen.
- `berufserfahrung`: Welche Stellen zeigen? In welcher Reihenfolge? Welche Aufgaben/Erfolge je Stelle zeigen + ggf. neu formulieren.
- `projekte_hervorheben`: Liste von Projekt-IDs (z.B. "8-n8n-builder"), die im Lebenslauf prominent erscheinen sollten.
- `skills_reihenfolge`: Skills aus dem Master in Reihenfolge der Relevanz für diese Stelle.
"""


class CustomBerufserfahrung(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: str
    firma: str
    von: str
    bis: Optional[str] = None
    standort: Optional[str] = None
    aufgaben: list[str] = Field(default_factory=list)
    erfolge: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class CustomProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    titel: str
    kurzbeschreibung: Optional[str] = None
    rolle: Optional[str] = None
    skills_fachlich: list[str] = Field(default_factory=list)


class CustomizedResume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    berufsprofil_zugespitzt: str = Field(description="2-3 Sätze, auf Stelle ausgerichtet.")
    berufserfahrung: list[CustomBerufserfahrung] = Field(description="Gefilterte/umformulierte Stellen in Anzeige-Reihenfolge.")
    projekte_hervorheben: list[str] = Field(description="Projekt-IDs in Reihenfolge der Anzeige.")
    skills_reihenfolge: list[str] = Field(description="Skill-Reihenfolge für die Skill-Sektion.")


def _master_to_prompt(profile: MasterProfile) -> str:
    """Convert MasterProfile to YAML text for LLM prompt, filtering hidden projects."""
    data = profile.model_dump(exclude_none=True)
    data["projekte"] = [
        p for p in data.get("projekte", [])
        if p.get("sichtbar_in_lebenslauf", True)
    ]
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def customize_resume(
    profile: MasterProfile, job_description: str, llm: LLMClient
) -> CustomizedResume:
    """Run LLM pass 1: select/reorder/refine Lebenslauf for this specific job."""
    master_text = _master_to_prompt(profile)
    user = (
        "MASTER-PROFIL:\n"
        f"{master_text}\n\n"
        "STELLENAUSSCHREIBUNG:\n"
        f"{job_description}\n\n"
        "Erstelle eine zugeschnittene Lebenslauf-Struktur. Nur aus dem Master schöpfen."
    )
    return llm.structured(
        system=CUSTOMIZE_SYSTEM_PROMPT,
        user=user,
        schema=CustomizedResume,
    )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_customize.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/tailoring/customize.py bewerber/tests/unit/test_customize.py
git commit -m "feat(tailoring): LLM customize Lebenslauf with no-fabrication constraint"
```

---

## Task 6: LLM Generate Anschreiben

**Files:**
- Create: `bewerber/src/bewerber/tailoring/anschreiben.py`
- Test: `bewerber/tests/unit/test_anschreiben.py`

LLM pass 2: generates a deutsches Anschreiben as Markdown. Reads `anschreiben_examples/*.txt` from the bewerber dir for few-shot stylistic guidance.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_anschreiben.py`:

```python
from pathlib import Path
from bewerber.tailoring.anschreiben import AnschreibenContent, generate_anschreiben, _collect_few_shot_examples


def test_collect_examples_returns_empty_when_dir_missing(tmp_path):
    examples = _collect_few_shot_examples(tmp_path / "nope")
    assert examples == []


def test_collect_examples_reads_txt_files_in_order(tmp_path):
    d = tmp_path / "examples"
    d.mkdir()
    (d / "02_lead.txt").write_text("Anschreiben Lead PM ...")
    (d / "01_ki.txt").write_text("Anschreiben KI Manager ...")
    examples = _collect_few_shot_examples(d)
    assert len(examples) == 2
    assert examples[0].startswith("Anschreiben KI")  # 01 first
    assert examples[1].startswith("Anschreiben Lead")


def test_generate_anschreiben_calls_llm_with_master_and_job(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = AnschreibenContent(
        anrede="Sehr geehrte Frau Müller,",
        einleitung="Mit großem Interesse...",
        hauptteil="Meine Erfahrung als Projektmanager...",
        schluss="Über die Einladung würde ich mich freuen.",
        gruss="Mit freundlichen Grüßen\nSteve Eigenwillig",
    )
    result = generate_anschreiben(
        master_yaml_text="person:\n  name: Steve",
        job_description="KI Manager bei BMW",
        kontakt_name="Anna Müller",
        few_shot_examples=["Beispiel-Anschreiben 1 ..."],
        llm=fake_llm,
    )
    assert result.anrede.startswith("Sehr geehrte")
    assert "Müller" in result.anrede

    args, kwargs = fake_llm.structured.call_args
    user_prompt = kwargs["user"]
    assert "KI Manager bei BMW" in user_prompt
    assert "Anna Müller" in user_prompt
    assert "Beispiel-Anschreiben 1" in user_prompt
    assert kwargs["schema"] is AnschreibenContent


def test_generate_anschreiben_falls_back_when_kontakt_missing(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = AnschreibenContent(
        anrede="Sehr geehrte Damen und Herren,",
        einleitung="x", hauptteil="x", schluss="x",
        gruss="Mit freundlichen Grüßen\nSteve",
    )
    result = generate_anschreiben(
        master_yaml_text="x",
        job_description="y",
        kontakt_name=None,
        few_shot_examples=[],
        llm=fake_llm,
    )
    user_prompt = fake_llm.structured.call_args.kwargs["user"]
    assert "kein konkreter Ansprechpartner" in user_prompt.lower() or "damen und herren" in user_prompt.lower()


def test_anschreiben_to_markdown():
    content = AnschreibenContent(
        anrede="Sehr geehrte Frau Müller,",
        einleitung="E1.",
        hauptteil="H1.\n\nH2.",
        schluss="S1.",
        gruss="Mit freundlichen Grüßen\nSteve",
    )
    md = content.to_markdown()
    assert "Sehr geehrte Frau Müller," in md
    assert "E1." in md
    assert "H1." in md
    assert "S1." in md
    assert "Mit freundlichen Grüßen" in md
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_anschreiben.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/tailoring/anschreiben.py`**

```python
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict

from bewerber.shared.llm import LLMClient


ANSCHREIBEN_SYSTEM_PROMPT = """Du bist ein erfahrener deutscher Karriere-Coach. Du verfasst ein professionelles deutsches Anschreiben.

REGELN:
1. Erfinde keine Erfahrungen oder Skills. Nur aus dem gegebenen Master-Profil schöpfen.
2. Authentisch und konkret — keine Floskeln wie "highly motivated team player".
3. Direkter Bezug zur ausgeschriebenen Stelle: was du konkret mitbringst (aus Master) und warum genau diese Firma.
4. Stil: höflich, professionell, "Sie"-Form, aber persönlich und nicht hölzern.
5. Wenn Stil-Beispiele vorliegen: lerne den Ton/Aufbau daraus, kopiere aber nicht.
6. Vier inhaltliche Abschnitte ohne Zwischenüberschriften:
   - Anrede (Frau/Herr <Nachname> oder "Sehr geehrte Damen und Herren")
   - Einleitung (1-2 Sätze: worauf bezieht sich Bewerbung, warum Interesse)
   - Hauptteil (3-5 Sätze: Was bringe ich mit, konkrete Erfolge aus Master)
   - Schluss (1-2 Sätze: Einladung zum Gespräch, höfliche Verabschiedung)
   - Gruss (Standard "Mit freundlichen Grüßen" + Name)
"""


class AnschreibenContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anrede: str = Field(description="Sehr geehrte Frau X / Herr Y / Damen und Herren,")
    einleitung: str = Field(description="1-2 Sätze: Bezug + Interesse")
    hauptteil: str = Field(description="3-5 Sätze, ggf. Absätze. Konkrete Erfolge aus Master.")
    schluss: str = Field(description="1-2 Sätze: Einladung zum Gespräch")
    gruss: str = Field(description="z.B. 'Mit freundlichen Grüßen\\nSteve Eigenwillig'")

    def to_markdown(self) -> str:
        """Combine all sections into a single Markdown document."""
        return (
            f"{self.anrede}\n\n"
            f"{self.einleitung}\n\n"
            f"{self.hauptteil}\n\n"
            f"{self.schluss}\n\n"
            f"{self.gruss}\n"
        )


def _collect_few_shot_examples(examples_dir: Path) -> list[str]:
    """Read all .txt files in examples_dir alphabetically (preserves NN_-prefix ordering)."""
    if not examples_dir.is_dir():
        return []
    files = sorted(examples_dir.glob("*.txt"))
    return [f.read_text(encoding="utf-8") for f in files]


def generate_anschreiben(
    master_yaml_text: str,
    job_description: str,
    kontakt_name: str | None,
    few_shot_examples: list[str],
    llm: LLMClient,
) -> AnschreibenContent:
    """Run LLM pass 2: generate Anschreiben as structured content."""
    examples_block = ""
    if few_shot_examples:
        examples_block = "BISHERIGE ANSCHREIBEN VOM BEWERBER (Stil-Referenz, NICHT kopieren):\n\n"
        for i, ex in enumerate(few_shot_examples, start=1):
            examples_block += f"--- Beispiel {i} ---\n{ex}\n\n"

    kontakt_hint = (
        f"Ansprechpartner laut Stellenausschreibung: {kontakt_name}. "
        f"Anrede entsprechend: 'Sehr geehrte/r Frau/Herr {kontakt_name.split()[-1] if kontakt_name else ''}'."
        if kontakt_name
        else "Es gibt kein konkreter Ansprechpartner — Anrede: 'Sehr geehrte Damen und Herren,'"
    )

    user = (
        "MASTER-PROFIL DES BEWERBERS:\n"
        f"{master_yaml_text}\n\n"
        "STELLENAUSSCHREIBUNG:\n"
        f"{job_description}\n\n"
        f"{kontakt_hint}\n\n"
        f"{examples_block}"
        "Verfasse das deutsche Anschreiben."
    )
    return llm.structured(
        system=ANSCHREIBEN_SYSTEM_PROMPT,
        user=user,
        schema=AnschreibenContent,
    )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_anschreiben.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/tailoring/anschreiben.py bewerber/tests/unit/test_anschreiben.py
git commit -m "feat(tailoring): LLM Anschreiben generator with few-shot stylistic source"
```

---

## Task 7: Lebenslauf HTML Template

**Files:**
- Create: `bewerber/templates/lebenslauf.html.j2`

A standalone HTML+CSS template for the Lebenslauf, rendered via Jinja2 then WeasyPrint. Self-contained styling (no external CSS files), modern German Lebenslauf layout.

- [ ] **Step 1: Create `bewerber/templates/lebenslauf.html.j2`**

```bash
mkdir -p /Users/steve/Documents/Bewerber_Assistent/bewerber/templates
```

Write to `bewerber/templates/lebenslauf.html.j2`:

```html
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Lebenslauf {{ profile.person.name }}</title>
<style>
@page { size: A4; margin: 1.5cm 2cm; }
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #222; }
h1 { font-size: 22pt; margin: 0 0 0.2em 0; font-weight: 600; color: #1a3a5c; }
h2 { font-size: 13pt; margin: 1.4em 0 0.4em 0; font-weight: 600; color: #1a3a5c; border-bottom: 1px solid #1a3a5c; padding-bottom: 2pt; }
h3 { font-size: 11pt; margin: 0.6em 0 0.1em 0; font-weight: 600; }
.contact { color: #555; font-size: 9.5pt; margin-bottom: 1em; }
.contact span { margin-right: 1.2em; }
.berufsprofil { font-style: italic; margin: 0.6em 0 0 0; }
.stelle { margin: 0.6em 0 0.8em 0; }
.stelle-meta { color: #555; font-size: 9.5pt; }
.firma { font-weight: 600; }
ul { margin: 0.2em 0 0.4em 1.3em; padding: 0; }
li { margin-bottom: 0.15em; }
.skills { line-height: 1.7; }
.skill-chip { display: inline-block; background: #e8eef5; padding: 1pt 6pt; margin: 0 4pt 4pt 0; border-radius: 3pt; font-size: 9pt; }
.projekt { margin: 0.5em 0 0.6em 0; }
.projekt-titel { font-weight: 600; }
.zweispaltig { display: flex; gap: 2em; }
.zweispaltig > div { flex: 1; }
</style>
</head>
<body>

<h1>{{ profile.person.name }}</h1>
<div class="contact">
{% if profile.person.email %}<span>📧 {{ profile.person.email }}</span>{% endif %}
{% if profile.person.phone %}<span>📞 {{ profile.person.phone }}</span>{% endif %}
{% if profile.person.adresse %}<span>📍 {{ profile.person.adresse }}</span>{% endif %}
{% if profile.person.linkedin %}<span>🔗 {{ profile.person.linkedin }}</span>{% endif %}
</div>

<p class="berufsprofil">{{ customized.berufsprofil_zugespitzt or profile.berufsprofil }}</p>

<h2>Berufserfahrung</h2>
{% for job in customized.berufserfahrung %}
<div class="stelle">
  <h3>{{ job.position }} — <span class="firma">{{ job.firma }}</span></h3>
  <div class="stelle-meta">{{ job.von }} – {{ job.bis or "heute" }}{% if job.standort %} · {{ job.standort }}{% endif %}</div>
  {% if job.aufgaben %}
  <ul>{% for a in job.aufgaben %}<li>{{ a }}</li>{% endfor %}</ul>
  {% endif %}
  {% if job.erfolge %}
  <ul>{% for e in job.erfolge %}<li><strong>{{ e }}</strong></li>{% endfor %}</ul>
  {% endif %}
</div>
{% endfor %}

{% if highlighted_projects %}
<h2>Ausgewählte Projekte</h2>
{% for p in highlighted_projects %}
<div class="projekt">
  <div class="projekt-titel">{{ p.titel }}</div>
  {% if p.kurzbeschreibung %}<div>{{ p.kurzbeschreibung }}</div>{% endif %}
  {% if p.rolle %}<div><em>Rolle:</em> {{ p.rolle }}</div>{% endif %}
  {% if p.skills_fachlich %}<div><em>Skills:</em> {{ p.skills_fachlich | join(", ") }}</div>{% endif %}
</div>
{% endfor %}
{% endif %}

<h2>Ausbildung</h2>
{% for edu in profile.ausbildung %}
<div class="stelle">
  <h3>{{ edu.abschluss or edu.art }}</h3>
  <div class="stelle-meta">{{ edu.institution }}{% if edu.jahr %} · {{ edu.jahr }}{% endif %}</div>
</div>
{% endfor %}

<div class="zweispaltig">
  <div>
    <h2>Skills</h2>
    <div class="skills">
      {% for skill in customized.skills_reihenfolge %}<span class="skill-chip">{{ skill }}</span>{% endfor %}
    </div>
  </div>
  <div>
    {% if profile.sprachen %}
    <h2>Sprachen</h2>
    <ul>
      {% for s in profile.sprachen %}<li>{{ s.sprache }} ({{ s.niveau }})</li>{% endfor %}
    </ul>
    {% endif %}
    {% if profile.zertifikate %}
    <h2>Zertifikate</h2>
    <ul>
      {% for z in profile.zertifikate %}<li>{{ z.name }}{% if z.aussteller %} — {{ z.aussteller }}{% endif %}</li>{% endfor %}
    </ul>
    {% endif %}
  </div>
</div>

</body>
</html>
```

- [ ] **Step 2: Manually verify template renders something sensible**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
python3 << 'EOF'
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
tpl = env.get_template("lebenslauf.html.j2")

# Build minimal placeholders
class P:
    person = type("P", (), {"name": "Test", "email": "t@x.de", "phone": "123", "adresse": "Adr", "linkedin": None})()
    berufsprofil = "Profil."
    ausbildung = []
    sprachen = []
    zertifikate = []
    projekte = []

class C:
    berufsprofil_zugespitzt = "Tailored."
    berufserfahrung = []
    skills_reihenfolge = ["Python", "Leadership"]

out = tpl.render(profile=P(), customized=C(), highlighted_projects=[])
assert "Test" in out
assert "Tailored." in out
assert "Python" in out
print("OK — template renders.")
EOF
```

Expected: "OK — template renders."

- [ ] **Step 3: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/templates/lebenslauf.html.j2
git commit -m "feat(templates): Lebenslauf HTML+CSS template (Jinja2)"
```

---

## Task 8: Anschreiben HTML Template

**Files:**
- Create: `bewerber/templates/anschreiben.html.j2`

German letter format: sender block, date right, recipient, Betreff, body, Gruß.

- [ ] **Step 1: Create `bewerber/templates/anschreiben.html.j2`**

Write to `bewerber/templates/anschreiben.html.j2`:

```html
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Anschreiben {{ profile.person.name }} — {{ firma }}</title>
<style>
@page { size: A4; margin: 2.5cm 2.5cm 2cm 2.5cm; }
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #222; }
.sender { font-size: 9pt; color: #555; margin-bottom: 2em; }
.sender div { margin: 0; }
.recipient { margin-bottom: 1.5em; }
.recipient div { margin: 0; }
.datum { text-align: right; margin-bottom: 1em; font-size: 10pt; color: #555; }
.betreff { font-weight: 600; margin: 1em 0 1.2em 0; }
.body p { margin: 0.6em 0; white-space: pre-wrap; }
.gruss { margin-top: 1.5em; white-space: pre-wrap; }
</style>
</head>
<body>

<div class="sender">
  <div>{{ profile.person.name }}</div>
  {% if profile.person.adresse %}<div>{{ profile.person.adresse }}</div>{% endif %}
  {% if profile.person.email %}<div>{{ profile.person.email }}</div>{% endif %}
  {% if profile.person.phone %}<div>{{ profile.person.phone }}</div>{% endif %}
</div>

<div class="recipient">
  <div>{{ firma }}</div>
  {% if kontakt_name %}<div>z. Hd. {{ kontakt_name }}</div>{% endif %}
</div>

<div class="datum">{{ datum }}</div>

<div class="betreff">Bewerbung als {{ rolle }}</div>

<div class="body">
  <p>{{ anschreiben.anrede }}</p>
  <p>{{ anschreiben.einleitung }}</p>
  <p>{{ anschreiben.hauptteil }}</p>
  <p>{{ anschreiben.schluss }}</p>
</div>

<div class="gruss">{{ anschreiben.gruss }}</div>

</body>
</html>
```

- [ ] **Step 2: Verify template renders**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
python3 << 'EOF'
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
tpl = env.get_template("anschreiben.html.j2")

class P:
    person = type("P", (), {"name": "Steve", "email": "s@x.de", "phone": "123", "adresse": "Leipzig"})()

class A:
    anrede = "Sehr geehrte Frau Müller,"
    einleitung = "Mit großem Interesse..."
    hauptteil = "Meine Erfahrung..."
    schluss = "Über die Einladung..."
    gruss = "Mit freundlichen Grüßen\nSteve"

out = tpl.render(profile=P(), anschreiben=A(), firma="BMW", rolle="KI Manager", datum="12.06.2026", kontakt_name="Anna Müller")
assert "Sehr geehrte Frau Müller" in out
assert "Mit freundlichen Grüßen" in out
assert "Bewerbung als KI Manager" in out
print("OK — Anschreiben template renders.")
EOF
```

Expected: "OK — Anschreiben template renders."

- [ ] **Step 3: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/templates/anschreiben.html.j2
git commit -m "feat(templates): Anschreiben HTML letter format template"
```

---

## Task 9: WeasyPrint Render Functions

**Files:**
- Create: `bewerber/src/bewerber/tailoring/render.py`
- Test: `bewerber/tests/unit/test_render.py`

Pure rendering: takes data, returns PDF bytes (or writes to file). No LLM, no side-effects on state.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_render.py`:

```python
from pathlib import Path
from bewerber.tailoring.render import render_lebenslauf, render_anschreiben
from bewerber.tailoring.customize import CustomizedResume, CustomBerufserfahrung
from bewerber.tailoring.anschreiben import AnschreibenContent
from bewerber.shared.profile_schema import (
    MasterProfile, Person, Berufserfahrung, Project, Ausbildung, Sprache, Zertifikat,
)


def _profile() -> MasterProfile:
    return MasterProfile(
        person=Person(name="Steve Eigenwillig", email="s@x.de", phone="+49 123",
                      adresse="Leipzig"),
        berufsprofil="Erfahrener Manager.",
        zielposition=["KI Manager"],
        ausbildung=[Ausbildung(art="Techniker", institution="RHS Chemnitz", jahr="2015")],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01", bis="2024-08",
                            aufgaben=["a1"], erfolge=["e1"], skills=["Python"]),
        ],
        projekte=[
            Project(id="1-x", titel="X", kurzbeschreibung="Beschreibung X",
                    rolle="Lead", skills_fachlich=["Python", "n8n"]),
        ],
        zertifikate=[Zertifikat(name="REFA", aussteller="REFA")],
        sprachen=[Sprache(sprache="Deutsch", niveau="C2")],
    )


def _customized() -> CustomizedResume:
    return CustomizedResume(
        berufsprofil_zugespitzt="Zugeschnitten.",
        berufserfahrung=[
            CustomBerufserfahrung(position="PM", firma="Acme", von="2020-01", bis="2024-08",
                                   aufgaben=["a1 (tailored)"], erfolge=["e1"], skills=["Python"]),
        ],
        projekte_hervorheben=["1-x"],
        skills_reihenfolge=["Python", "n8n", "Leadership"],
    )


def test_render_lebenslauf_returns_pdf_bytes(tmp_path):
    pdf = render_lebenslauf(_profile(), _customized())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000  # has actual content


def test_render_lebenslauf_includes_highlighted_projects():
    """Projects in projekte_hervorheben must appear in PDF (we check via text extraction)."""
    import pdfplumber
    import io
    pdf_bytes = render_lebenslauf(_profile(), _customized())
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    assert "Steve Eigenwillig" in text
    assert "Zugeschnitten." in text
    assert "Acme" in text
    assert "X" in text  # project title
    assert "Python" in text


def test_render_anschreiben_returns_pdf_bytes():
    anschreiben = AnschreibenContent(
        anrede="Sehr geehrte Damen und Herren,",
        einleitung="Mit großem Interesse...",
        hauptteil="Meine Erfahrung als Projektmanager bei Acme...",
        schluss="Über die Einladung würde ich mich freuen.",
        gruss="Mit freundlichen Grüßen\nSteve Eigenwillig",
    )
    pdf = render_anschreiben(
        _profile(),
        anschreiben,
        firma="BMW Group",
        rolle="KI Manager",
        datum="12.06.2026",
        kontakt_name=None,
    )
    assert pdf.startswith(b"%PDF")

    import pdfplumber
    import io
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        text = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "Sehr geehrte Damen und Herren" in text
    assert "Bewerbung als KI Manager" in text
    assert "BMW Group" in text
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_render.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/tailoring/render.py`**

```python
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from bewerber.shared.profile_schema import MasterProfile
from bewerber.tailoring.customize import CustomizedResume
from bewerber.tailoring.anschreiben import AnschreibenContent


TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_lebenslauf(profile: MasterProfile, customized: CustomizedResume) -> bytes:
    """Render Lebenslauf as PDF bytes."""
    highlighted = _select_highlighted_projects(profile, customized.projekte_hervorheben)
    html_text = _env().get_template("lebenslauf.html.j2").render(
        profile=profile,
        customized=customized,
        highlighted_projects=highlighted,
    )
    return HTML(string=html_text).write_pdf()


def render_anschreiben(
    profile: MasterProfile,
    anschreiben: AnschreibenContent,
    firma: str,
    rolle: str,
    datum: str,
    kontakt_name: str | None,
) -> bytes:
    """Render Anschreiben as PDF bytes."""
    html_text = _env().get_template("anschreiben.html.j2").render(
        profile=profile,
        anschreiben=anschreiben,
        firma=firma,
        rolle=rolle,
        datum=datum,
        kontakt_name=kontakt_name,
    )
    return HTML(string=html_text).write_pdf()


def _select_highlighted_projects(profile: MasterProfile, ids: list[str]) -> list:
    """Return projekte from profile matching ids, in given order."""
    by_id = {p.id: p for p in profile.projekte if p.sichtbar_in_lebenslauf}
    out = []
    for pid in ids:
        if pid in by_id:
            out.append(by_id[pid])
    return out
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_render.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/tailoring/render.py bewerber/tests/unit/test_render.py
git commit -m "feat(tailoring): WeasyPrint PDF rendering for Lebenslauf and Anschreiben"
```

---

## Task 10: Orchestrator + Audit Log

**Files:**
- Create: `bewerber/src/bewerber/tailoring/orchestrator.py`
- Test: `bewerber/tests/unit/test_orchestrator.py`

End-to-end function called by CLI. Composes posting → customize → anschreiben → render → save.

- [ ] **Step 1: Write failing test**

Write to `bewerber/tests/unit/test_orchestrator.py`:

```python
import json
import yaml
from pathlib import Path
from bewerber.tailoring.orchestrator import tailor, TailorInput, TailorResult
from bewerber.tailoring.customize import CustomizedResume, CustomBerufserfahrung
from bewerber.tailoring.anschreiben import AnschreibenContent
from bewerber.shared.profile_schema import (
    MasterProfile, Person, Berufserfahrung,
)


def _write_master(tmp_path: Path) -> Path:
    profile = MasterProfile(
        person=Person(name="Steve Eigenwillig", email="s@x.de"),
        berufsprofil="Profil.",
        zielposition=[],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01"),
        ],
    )
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml.safe_dump(profile.model_dump(), allow_unicode=True))
    return path


def test_tailor_full_pipeline_with_text_input(tmp_path, mocker, monkeypatch):
    workspace = tmp_path / "ws"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = tmp_path / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    master_path = bewerber_dir / "master_profile.yaml"
    master_path.write_text(_write_master(bewerber_dir).read_text())

    # Mock LLM passes
    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="Tailored profil.",
        berufserfahrung=[CustomBerufserfahrung(position="PM", firma="Acme", von="2020-01", bis=None,
                                                aufgaben=["a"], erfolge=[], skills=[])],
        projekte_hervorheben=[],
        skills_reihenfolge=["Python"],
    ))
    mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="Sehr geehrte Damen und Herren,",
        einleitung="E.", hauptteil="H.", schluss="S.",
        gruss="Mit freundlichen Grüßen\nSteve",
    ))

    job_text = "KI Manager bei BMW. Python gesucht."
    result = tailor(TailorInput(
        posting_text=job_text,
        firma="BMW Group",
        rolle="KI Manager",
        datum="2026-06-12",
        kontakt_name=None,
        source_url=None,
        snapshot_dir=None,
        llm=mocker.Mock(),
    ))

    assert isinstance(result, TailorResult)
    out_dir = result.output_dir
    assert out_dir.name == "2026-06-12_BMW-Group_KI-Manager"
    assert (out_dir / "lebenslauf.pdf").is_file()
    assert (out_dir / "lebenslauf.html").is_file()
    assert (out_dir / "anschreiben.pdf").is_file()
    assert (out_dir / "anschreiben.md").is_file()
    assert (out_dir / "tailoring_log.json").is_file()
    assert (out_dir / "posting_meta.yaml").is_file()
    assert (out_dir / "posting.txt").is_file()

    # Audit log content
    log = json.loads((out_dir / "tailoring_log.json").read_text())
    assert log["firma"] == "BMW Group"
    assert log["rolle"] == "KI Manager"
    assert "customized" in log
    assert "anschreiben" in log

    # Posting meta has the URL field even when None
    meta = yaml.safe_load((out_dir / "posting_meta.yaml").read_text())
    assert meta["firma"] == "BMW Group"
    assert meta["source_url"] is None


def test_tailor_loads_anschreiben_few_shot_examples(tmp_path, mocker, monkeypatch):
    workspace = tmp_path / "ws"
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = tmp_path / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    examples = bewerber_dir / "anschreiben_examples"
    examples.mkdir()
    (examples / "01_x.txt").write_text("Beispiel-Anschreiben.")

    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    _write_master(bewerber_dir).rename(bewerber_dir / "master_profile.yaml")

    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="x", berufserfahrung=[], projekte_hervorheben=[], skills_reihenfolge=[],
    ))
    gen = mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="x", einleitung="x", hauptteil="x", schluss="x", gruss="x",
    ))

    tailor(TailorInput(
        posting_text="job", firma="X", rolle="Y", datum="2026-06-12",
        kontakt_name=None, source_url=None, snapshot_dir=None, llm=mocker.Mock(),
    ))

    # Verify few_shot_examples was passed
    args, kwargs = gen.call_args
    assert kwargs["few_shot_examples"] == ["Beispiel-Anschreiben."]
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_orchestrator.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `bewerber/src/bewerber/tailoring/orchestrator.py`**

```python
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml

from bewerber.shared.llm import LLMClient
from bewerber.shared.paths import Paths
from bewerber.shared.profile_schema import MasterProfile
from bewerber.shared.slug import bewerbungsordner_name
from bewerber.tailoring.anschreiben import (
    AnschreibenContent,
    generate_anschreiben,
    _collect_few_shot_examples,
)
from bewerber.tailoring.customize import CustomizedResume, customize_resume
from bewerber.tailoring.render import render_anschreiben, render_lebenslauf


@dataclass
class TailorInput:
    posting_text: str
    firma: str
    rolle: str
    datum: str  # YYYY-MM-DD
    kontakt_name: Optional[str]
    source_url: Optional[str]
    snapshot_dir: Optional[Path]  # if URL was snapshotted, location of posting.html/pdf
    llm: LLMClient


@dataclass
class TailorResult:
    output_dir: Path
    lebenslauf_pdf: Path
    anschreiben_pdf: Path
    customized: CustomizedResume
    anschreiben: AnschreibenContent


def tailor(inp: TailorInput) -> TailorResult:
    """Run full tailoring pipeline: customize, anschreiben, render, save."""
    paths = Paths()
    master = _load_master(paths.master_profile)
    master_yaml_text = paths.master_profile.read_text(encoding="utf-8")

    customized = customize_resume(master, inp.posting_text, llm=inp.llm)
    few_shot = _collect_few_shot_examples(paths.anschreiben_examples)
    anschreiben = generate_anschreiben(
        master_yaml_text=master_yaml_text,
        job_description=inp.posting_text,
        kontakt_name=inp.kontakt_name,
        few_shot_examples=few_shot,
        llm=inp.llm,
    )

    out_dir = paths.bewerbungen / bewerbungsordner_name(inp.datum, inp.firma, inp.rolle)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Render PDFs and persist sources
    datum_de = _to_german_date(inp.datum)
    lebenslauf_pdf = render_lebenslauf(master, customized)
    anschreiben_pdf = render_anschreiben(
        master, anschreiben,
        firma=inp.firma, rolle=inp.rolle, datum=datum_de, kontakt_name=inp.kontakt_name,
    )
    (out_dir / "lebenslauf.pdf").write_bytes(lebenslauf_pdf)
    (out_dir / "anschreiben.pdf").write_bytes(anschreiben_pdf)
    (out_dir / "lebenslauf.html").write_text(_lebenslauf_html(master, customized), encoding="utf-8")
    (out_dir / "anschreiben.md").write_text(anschreiben.to_markdown(), encoding="utf-8")
    (out_dir / "posting.txt").write_text(inp.posting_text, encoding="utf-8")

    # Move snapshot (posting.html/posting.pdf) into output dir if it was generated
    if inp.snapshot_dir is not None:
        for fname in ("posting.html", "posting.pdf"):
            src = inp.snapshot_dir / fname
            if src.is_file():
                shutil.move(str(src), str(out_dir / fname))

    # Posting metadata
    meta = {
        "firma": inp.firma,
        "rolle": inp.rolle,
        "datum": inp.datum,
        "kontakt_name": inp.kontakt_name,
        "source_url": inp.source_url,
    }
    (out_dir / "posting_meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # Audit log
    log = {
        "firma": inp.firma,
        "rolle": inp.rolle,
        "datum": inp.datum,
        "customized": customized.model_dump(),
        "anschreiben": anschreiben.model_dump(),
    }
    (out_dir / "tailoring_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return TailorResult(
        output_dir=out_dir,
        lebenslauf_pdf=out_dir / "lebenslauf.pdf",
        anschreiben_pdf=out_dir / "anschreiben.pdf",
        customized=customized,
        anschreiben=anschreiben,
    )


def _load_master(path: Path) -> MasterProfile:
    """Load and validate master_profile.yaml."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return MasterProfile(**data)


def _lebenslauf_html(master: MasterProfile, customized: CustomizedResume) -> str:
    """Render Lebenslauf HTML source (without PDF conversion) for later editing."""
    from bewerber.tailoring.render import _env, _select_highlighted_projects
    highlighted = _select_highlighted_projects(master, customized.projekte_hervorheben)
    return _env().get_template("lebenslauf.html.j2").render(
        profile=master, customized=customized, highlighted_projects=highlighted,
    )


def _to_german_date(iso: str) -> str:
    """`2026-06-12` → `12.06.2026`"""
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_orchestrator.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/tailoring/orchestrator.py bewerber/tests/unit/test_orchestrator.py
git commit -m "feat(tailoring): orchestrator composes pipeline + audit log"
```

---

## Task 11: Wire `bewerber tailor` CLI Command

**Files:**
- Modify: `bewerber/src/bewerber/cli.py`
- Test: `bewerber/tests/unit/test_cli.py` (extend)

CLI accepts either `--url URL` (snapshot via Playwright) or `--posting-file PATH` (read txt/pdf/docx). Required: `--firma`, `--rolle`. Optional: `--kontakt`, `--datum` (defaults to today).

- [ ] **Step 1: Extend `bewerber/tests/unit/test_cli.py`**

Append:

```python
def test_tailor_requires_firma_and_rolle(mocker):
    runner = CliRunner()
    result = runner.invoke(main, ["tailor", "--posting-file", "doesnotmatter.txt"])
    assert result.exit_code != 0
    assert "firma" in result.output.lower() or "missing" in result.output.lower()


def test_tailor_from_file_invokes_orchestrator(tmp_path, monkeypatch, mocker):
    posting = tmp_path / "posting.txt"
    posting.write_text("KI Manager bei BMW. Python gesucht.")

    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)
    fake_tailor = mocker.patch("bewerber.cli.tailor")
    fake_result = mocker.Mock()
    fake_result.output_dir = tmp_path / "out"
    fake_result.lebenslauf_pdf = tmp_path / "out" / "lebenslauf.pdf"
    fake_result.anschreiben_pdf = tmp_path / "out" / "anschreiben.pdf"
    fake_tailor.return_value = fake_result

    runner = CliRunner()
    result = runner.invoke(main, [
        "tailor",
        "--posting-file", str(posting),
        "--firma", "BMW Group",
        "--rolle", "KI Manager",
        "--datum", "2026-06-12",
        "--kontakt", "Anna Müller",
    ])
    assert result.exit_code == 0, result.output

    _, kwargs = fake_tailor.call_args
    inp = fake_tailor.call_args.args[0]
    assert inp.firma == "BMW Group"
    assert inp.rolle == "KI Manager"
    assert inp.datum == "2026-06-12"
    assert inp.kontakt_name == "Anna Müller"
    assert inp.source_url is None
    assert "KI Manager bei BMW" in inp.posting_text


def test_tailor_from_url_calls_snapshot(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))

    fake_snap = mocker.patch("bewerber.cli.snapshot_url", return_value="Posting text from URL.")
    fake_tailor = mocker.patch("bewerber.cli.tailor")
    fake_result = mocker.Mock()
    fake_result.output_dir = tmp_path / "out"
    fake_result.lebenslauf_pdf = tmp_path / "out" / "lebenslauf.pdf"
    fake_result.anschreiben_pdf = tmp_path / "out" / "anschreiben.pdf"
    fake_tailor.return_value = fake_result

    runner = CliRunner()
    result = runner.invoke(main, [
        "tailor",
        "--url", "https://example.com/job/123",
        "--firma", "BMW",
        "--rolle", "Manager",
        "--datum", "2026-06-12",
    ])
    assert result.exit_code == 0, result.output
    fake_snap.assert_called_once()
    inp = fake_tailor.call_args.args[0]
    assert inp.source_url == "https://example.com/job/123"
    assert inp.posting_text.startswith("Posting text from URL")
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 3 new tests fail.

- [ ] **Step 3: Update `bewerber/src/bewerber/cli.py`**

Add imports near the existing block (alphabetical with `bewerber.profile.*`):

```python
import tempfile
from datetime import date
from pathlib import Path
from bewerber.tailoring.orchestrator import tailor, TailorInput
from bewerber.tailoring.posting import read_posting_from_file
from bewerber.tailoring.snapshot import snapshot_url
```

Add the new command at the bottom of `main` group (after existing commands, before `if __name__ == "__main__":`):

```python
@main.command("tailor")
@click.option("--url", help="URL der Stellenausschreibung (wird via Playwright gesnapshotet).")
@click.option("--posting-file", "posting_file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Pfad zu einer Ausschreibung als .txt/.pdf/.docx.")
@click.option("--firma", required=True, help="Firmenname (für Ordnername + Anschreiben).")
@click.option("--rolle", required=True, help="Rollenbezeichnung (für Ordnername + Betreff).")
@click.option("--kontakt", "kontakt_name", help="Name der Ansprechperson (für Anrede).")
@click.option("--datum", help="Datum YYYY-MM-DD (default: heute).")
def cmd_tailor(url, posting_file, firma, rolle, kontakt_name, datum):
    """Erzeugt tailored Lebenslauf + Anschreiben für eine Stellenausschreibung."""
    if not url and not posting_file:
        click.echo("Fehler: --url ODER --posting-file muss angegeben werden.")
        raise click.exceptions.Exit(1)
    if url and posting_file:
        click.echo("Fehler: --url und --posting-file nicht gleichzeitig.")
        raise click.exceptions.Exit(1)

    datum = datum or date.today().isoformat()
    llm = LLMClient()
    snapshot_dir: Path | None = None

    if posting_file:
        posting = read_posting_from_file(posting_file)
        posting_text = posting.description
        source_url = None
        click.echo(f"Lese Ausschreibung aus {posting_file.name} …")
    else:
        click.echo(f"Snapshot {url} …")
        snapshot_dir = Path(tempfile.mkdtemp(prefix="bewerber-snap-"))
        posting_text = snapshot_url(url, snapshot_dir)
        source_url = url

    click.echo("Generiere Lebenslauf + Anschreiben …")
    result = tailor(TailorInput(
        posting_text=posting_text,
        firma=firma, rolle=rolle, datum=datum,
        kontakt_name=kontakt_name,
        source_url=source_url,
        snapshot_dir=snapshot_dir,
        llm=llm,
    ))
    click.echo(f"\n✔ Bewerbungsordner: {result.output_dir}")
    click.echo(f"  • Lebenslauf:    {result.lebenslauf_pdf.name}")
    click.echo(f"  • Anschreiben:   {result.anschreiben_pdf.name}")
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: 11 passed (8 prior + 3 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/cli.py bewerber/tests/unit/test_cli.py
git commit -m "feat(cli): wire bewerber tailor command (URL or file input)"
```

---

## Task 12: `bewerber tailor --rebuild` (PDFs only, no LLM)

**Files:**
- Modify: `bewerber/src/bewerber/cli.py`
- Modify: `bewerber/src/bewerber/tailoring/orchestrator.py` (add rebuild_pdfs function)
- Test: extend `bewerber/tests/unit/test_orchestrator.py`

After the user manually edits `lebenslauf.html` or `anschreiben.md` in the bewerbungsordner, `--rebuild` regenerates the PDFs without LLM cost.

- [ ] **Step 1: Append test**

Append to `bewerber/tests/unit/test_orchestrator.py`:

```python
from bewerber.tailoring.orchestrator import rebuild_pdfs


def test_rebuild_pdfs_from_edited_html_and_md(tmp_path):
    out_dir = tmp_path / "2026-06-12_BMW_KI"
    out_dir.mkdir()
    (out_dir / "lebenslauf.html").write_text(
        "<!DOCTYPE html><html><body><h1>Manually edited CV</h1></body></html>",
        encoding="utf-8",
    )
    (out_dir / "anschreiben.md").write_text("# Edited\n\nManuell editiert.\n")
    (out_dir / "posting_meta.yaml").write_text(
        "firma: BMW\nrolle: KI Manager\ndatum: '2026-06-12'\nkontakt_name: null\nsource_url: null\n"
    )

    rebuild_pdfs(out_dir)

    pdf_l = (out_dir / "lebenslauf.pdf").read_bytes()
    pdf_a = (out_dir / "anschreiben.pdf").read_bytes()
    assert pdf_l.startswith(b"%PDF")
    assert pdf_a.startswith(b"%PDF")

    import pdfplumber, io
    with pdfplumber.open(io.BytesIO(pdf_l)) as p:
        lt = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "Manually edited CV" in lt
    with pdfplumber.open(io.BytesIO(pdf_a)) as p:
        at = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "Manuell editiert" in at
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_orchestrator.py::test_rebuild_pdfs_from_edited_html_and_md -v
```

Expected: AttributeError on `rebuild_pdfs`.

- [ ] **Step 3: Append to `bewerber/src/bewerber/tailoring/orchestrator.py`**

```python
from markdown_it import MarkdownIt
from weasyprint import HTML


def rebuild_pdfs(out_dir: Path) -> None:
    """Re-render Lebenslauf and Anschreiben PDFs from the edited HTML/MD sources.

    Reads `out_dir/lebenslauf.html` and `out_dir/anschreiben.md`. The Anschreiben
    markdown is rendered to a minimal HTML page (uses Anschreiben CSS from the
    original template).
    """
    lebenslauf_html_path = out_dir / "lebenslauf.html"
    anschreiben_md_path = out_dir / "anschreiben.md"

    if lebenslauf_html_path.is_file():
        html_text = lebenslauf_html_path.read_text(encoding="utf-8")
        (out_dir / "lebenslauf.pdf").write_bytes(HTML(string=html_text).write_pdf())

    if anschreiben_md_path.is_file():
        md_text = anschreiben_md_path.read_text(encoding="utf-8")
        body_html = MarkdownIt().render(md_text)
        full_html = _ANSCHREIBEN_REBUILD_TEMPLATE.format(body=body_html)
        (out_dir / "anschreiben.pdf").write_bytes(HTML(string=full_html).write_pdf())


_ANSCHREIBEN_REBUILD_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4; margin: 2.5cm 2.5cm 2cm 2.5cm; }}
body {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #222; }}
h1, h2, h3 {{ margin: 0.6em 0 0.4em 0; }}
p {{ margin: 0.6em 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/unit/test_orchestrator.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Append CLI test**

Append to `bewerber/tests/unit/test_cli.py`:

```python
def test_tailor_rebuild_calls_rebuild_pdfs(tmp_path, monkeypatch, mocker):
    out_dir = tmp_path / "2026-06-12_BMW_KI"
    out_dir.mkdir()
    (out_dir / "lebenslauf.html").write_text("<html><body>test</body></html>")

    fake_rebuild = mocker.patch("bewerber.cli.rebuild_pdfs")
    runner = CliRunner()
    result = runner.invoke(main, ["tailor", "--rebuild", str(out_dir)])
    assert result.exit_code == 0, result.output
    fake_rebuild.assert_called_once_with(out_dir)
```

- [ ] **Step 6: Update CLI — modify `bewerber/src/bewerber/cli.py`**

Add to the imports section:

```python
from bewerber.tailoring.orchestrator import rebuild_pdfs
```

Modify the `cmd_tailor` function: add a `--rebuild` argument and short-circuit logic. Replace the existing `cmd_tailor` decorator stack with:

```python
@main.command("tailor")
@click.option("--url", help="URL der Stellenausschreibung (wird via Playwright gesnapshotet).")
@click.option("--posting-file", "posting_file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Pfad zu einer Ausschreibung als .txt/.pdf/.docx.")
@click.option("--firma", help="Firmenname (für Ordnername + Anschreiben).")
@click.option("--rolle", help="Rollenbezeichnung (für Ordnername + Betreff).")
@click.option("--kontakt", "kontakt_name", help="Name der Ansprechperson (für Anrede).")
@click.option("--datum", help="Datum YYYY-MM-DD (default: heute).")
@click.option("--rebuild", "rebuild_dir", type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Nur PDFs neu aus dem Bewerbungsordner rendern (keine LLM-Aufrufe).")
def cmd_tailor(url, posting_file, firma, rolle, kontakt_name, datum, rebuild_dir):
    """Erzeugt tailored Lebenslauf + Anschreiben für eine Stellenausschreibung."""
    if rebuild_dir:
        click.echo(f"Re-rendere PDFs aus {rebuild_dir} …")
        rebuild_pdfs(rebuild_dir)
        click.echo("Fertig.")
        return

    if not url and not posting_file:
        click.echo("Fehler: --url ODER --posting-file muss angegeben werden (oder --rebuild).")
        raise click.exceptions.Exit(1)
    if url and posting_file:
        click.echo("Fehler: --url und --posting-file nicht gleichzeitig.")
        raise click.exceptions.Exit(1)
    if not firma or not rolle:
        click.echo("Fehler: --firma und --rolle sind erforderlich.")
        raise click.exceptions.Exit(1)

    datum = datum or date.today().isoformat()
    llm = LLMClient()
    snapshot_dir: Path | None = None

    if posting_file:
        posting = read_posting_from_file(posting_file)
        posting_text = posting.description
        source_url = None
        click.echo(f"Lese Ausschreibung aus {posting_file.name} …")
    else:
        click.echo(f"Snapshot {url} …")
        snapshot_dir = Path(tempfile.mkdtemp(prefix="bewerber-snap-"))
        posting_text = snapshot_url(url, snapshot_dir)
        source_url = url

    click.echo("Generiere Lebenslauf + Anschreiben …")
    result = tailor(TailorInput(
        posting_text=posting_text,
        firma=firma, rolle=rolle, datum=datum,
        kontakt_name=kontakt_name,
        source_url=source_url,
        snapshot_dir=snapshot_dir,
        llm=llm,
    ))
    click.echo(f"\n✔ Bewerbungsordner: {result.output_dir}")
    click.echo(f"  • Lebenslauf:    {result.lebenslauf_pdf.name}")
    click.echo(f"  • Anschreiben:   {result.anschreiben_pdf.name}")
```

Note: `firma` and `rolle` are no longer `required=True` at the Click level because `--rebuild` doesn't need them. The function checks them only on the LLM path.

Also update the earlier failing test `test_tailor_requires_firma_and_rolle` — since `required=True` was removed, that test now needs to expect a non-zero exit code from the manual check. The test as written already checks `exit_code != 0` and the message contains "firma" or "missing" — our new error message `"Fehler: --firma und --rolle sind erforderlich."` contains "firma", so the test should still pass. Confirm.

- [ ] **Step 7: Run, verify all pass**

```bash
pytest tests/unit/test_cli.py tests/unit/test_orchestrator.py -v
```

Expected: 12 + 3 = 15 passed.

- [ ] **Step 8: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/src/bewerber/cli.py bewerber/src/bewerber/tailoring/orchestrator.py bewerber/tests/unit/test_cli.py bewerber/tests/unit/test_orchestrator.py
git commit -m "feat(tailoring): --rebuild regenerates PDFs from edited HTML/MD without LLM"
```

---

## Task 13: End-to-End Integration Test

**Files:**
- Create: `bewerber/tests/integration/test_tailor_e2e.py`

Drives the full CLI (mocked LLM) and verifies all artifacts land in the Bewerbungsordner.

- [ ] **Step 1: Write test**

Write to `bewerber/tests/integration/test_tailor_e2e.py`:

```python
import io
import yaml
from pathlib import Path
from click.testing import CliRunner
import pdfplumber

from bewerber.cli import main
from bewerber.shared.profile_schema import (
    MasterProfile, Person, Berufserfahrung, Ausbildung, Sprache, Zertifikat, Project,
)
from bewerber.tailoring.customize import CustomizedResume, CustomBerufserfahrung
from bewerber.tailoring.anschreiben import AnschreibenContent


def test_full_tailor_workflow(tmp_path, monkeypatch, mocker):
    workspace = tmp_path / "Bewerber_Assistent"
    documents = tmp_path
    bewerber_dir = workspace / "bewerber"
    bewerber_dir.mkdir(parents=True)
    bu = documents / "Bewerbungsunterlagen"
    (bu / "Bewerbungen").mkdir(parents=True)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(workspace))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(documents))

    # Master profile with realistic data
    profile = MasterProfile(
        person=Person(name="Steve Eigenwillig", email="s.eigenwillig@yahoo.de",
                      phone="+49 1735808126", adresse="Flemmingstr. 4, Leipzig"),
        berufsprofil="Erfahrener Projekt- und Prozessmanager.",
        zielposition=["KI Manager"],
        ausbildung=[Ausbildung(art="Schule", institution="RHS Chemnitz",
                                abschluss="Techniker Maschinenbau", jahr="2015")],
        berufserfahrung=[
            Berufserfahrung(position="Vertriebsleiter", firma="Magna Glaskeramik GmbH",
                            von="2020-10", bis="2024-08", aufgaben=["Team führen"],
                            erfolge=["Umsatzsteigerung 10%"], skills=["CRM"]),
        ],
        projekte=[
            Project(id="8-n8n-builder", titel="n8n Builder",
                    kurzbeschreibung="Workflow-Automatisierung.",
                    rolle="Konzeption + Implementierung",
                    skills_fachlich=["n8n", "Python"], sichtbar_in_lebenslauf=True),
        ],
        zertifikate=[Zertifikat(name="REFA", aussteller="REFA")],
        sprachen=[Sprache(sprache="Deutsch", niveau="C2"),
                  Sprache(sprache="Englisch", niveau="B2")],
    )
    (bewerber_dir / "master_profile.yaml").write_text(
        yaml.safe_dump(profile.model_dump(), allow_unicode=True),
        encoding="utf-8",
    )

    # Posting file
    posting_file = tmp_path / "posting.txt"
    posting_file.write_text(
        "KI Manager (m/w/d) bei BMW Group, München.\n"
        "Verantwortung: KI-Roadmap, Cross-functional Teams.\n"
        "Anforderungen: Projekterfahrung, Python-Grundlagen.\n"
    )

    # Mock LLM at orchestrator
    mocker.patch("bewerber.tailoring.orchestrator.customize_resume", return_value=CustomizedResume(
        berufsprofil_zugespitzt="Erfahrener Projektmanager mit KI-Automatisierungsschwerpunkt.",
        berufserfahrung=[CustomBerufserfahrung(
            position="Vertriebsleiter & Projektmanager",
            firma="Magna Glaskeramik GmbH",
            von="2020-10", bis="2024-08",
            aufgaben=["Internationales Team führen", "CRM-Einführung"],
            erfolge=["Umsatz +10%, Lead-Transparenz +20%"],
            skills=["Team-Führung", "CRM"],
        )],
        projekte_hervorheben=["8-n8n-builder"],
        skills_reihenfolge=["Projektmanagement", "n8n", "Python", "KI-Automatisierung"],
    ))
    mocker.patch("bewerber.tailoring.orchestrator.generate_anschreiben", return_value=AnschreibenContent(
        anrede="Sehr geehrte Damen und Herren,",
        einleitung="Mit großem Interesse habe ich Ihre Ausschreibung gelesen.",
        hauptteil="Meine Erfahrung als Projektmanager bei Magna sowie meine "
                  "praktische Arbeit mit n8n-Workflows passen zur KI-Manager-Rolle.",
        schluss="Über die Einladung zum Gespräch würde ich mich sehr freuen.",
        gruss="Mit freundlichen Grüßen\nSteve Eigenwillig",
    ))
    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)

    runner = CliRunner()
    result = runner.invoke(main, [
        "tailor",
        "--posting-file", str(posting_file),
        "--firma", "BMW Group",
        "--rolle", "KI Manager",
        "--datum", "2026-06-12",
    ])
    assert result.exit_code == 0, result.output

    out_dir = bu / "Bewerbungen" / "2026-06-12_BMW-Group_KI-Manager"
    assert out_dir.is_dir()

    # All expected artifacts exist
    for name in ("lebenslauf.pdf", "lebenslauf.html", "anschreiben.pdf",
                 "anschreiben.md", "posting.txt", "posting_meta.yaml",
                 "tailoring_log.json"):
        assert (out_dir / name).is_file(), f"missing: {name}"

    # PDFs contain expected text
    with pdfplumber.open(io.BytesIO((out_dir / "lebenslauf.pdf").read_bytes())) as p:
        cv_text = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "Steve Eigenwillig" in cv_text
    assert "Magna" in cv_text
    assert "n8n Builder" in cv_text
    assert "KI-Automatisierung" in cv_text or "Automatisierung" in cv_text

    with pdfplumber.open(io.BytesIO((out_dir / "anschreiben.pdf").read_bytes())) as p:
        ans_text = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "BMW Group" in ans_text
    assert "Bewerbung als KI Manager" in ans_text
    assert "Sehr geehrte Damen und Herren" in ans_text
    assert "Mit freundlichen Grüßen" in ans_text
```

- [ ] **Step 2: Run full suite**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
pytest -v
```

Expected: all tests pass (~64 total: 48 from Plan A + 16 from Plan C).

- [ ] **Step 3: Commit**

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/tests/integration/test_tailor_e2e.py
git commit -m "test(tailoring): end-to-end CLI workflow integration test"
```

---

## Task 14: Smoke Run Against Steve's Real Posting (user-facing)

This is the user-facing acceptance step. Requires real OpenAI API key.

- [ ] **Step 1: Confirm posting source**

Decide with Steve: is the Ausschreibung available as URL, PDF, DOCX, or plain text?

- If URL: prepare to use `--url`.
- If file: copy/paste into `/tmp/posting.txt` (or use the original file directly).

- [ ] **Step 2: Run `bewerber tailor`**

```bash
cd /Users/steve/Documents/Bewerber_Assistent/bewerber
source .venv/bin/activate
PYTHONPATH="/Users/steve/Documents/Bewerber_Assistent/bewerber/src" python3 -m bewerber.cli tailor \
  --posting-file "/path/to/posting.txt" \
  --firma "FIRMA" \
  --rolle "ROLLE" \
  --kontakt "Vorname Nachname"
```

Substitute the real values. If the posting is at a URL:

```bash
PYTHONPATH="/Users/steve/Documents/Bewerber_Assistent/bewerber/src" python3 -m bewerber.cli tailor \
  --url "https://example.com/job/123" \
  --firma "FIRMA" \
  --rolle "ROLLE"
```

Expected: Two LLM calls (~30s total). Output:
```
Lese Ausschreibung aus posting.txt …
Generiere Lebenslauf + Anschreiben …
✔ Bewerbungsordner: /Users/steve/Documents/Bewerbungsunterlagen/Bewerbungen/2026-06-12_FIRMA_ROLLE
  • Lebenslauf:    lebenslauf.pdf
  • Anschreiben:   anschreiben.pdf
```

- [ ] **Step 3: Open the PDFs and review**

```bash
open "/Users/steve/Documents/Bewerbungsunterlagen/Bewerbungen/2026-06-12_FIRMA_ROLLE/lebenslauf.pdf"
open "/Users/steve/Documents/Bewerbungsunterlagen/Bewerbungen/2026-06-12_FIRMA_ROLLE/anschreiben.pdf"
```

User review criteria:
- Lebenslauf: Are berufsprofil, berufserfahrung, projekte sensibly tailored to the job? Any obvious hallucinations (claims not in master)?
- Anschreiben: Does the Anrede match the kontakt? Is the Hauptteil specific (not generic)? Is the Stil consistent with prior Anschreiben (if anschreiben_examples were set)?

- [ ] **Step 4: If edits needed, regenerate PDFs**

Open `lebenslauf.html` and/or `anschreiben.md` in editor, make changes, then:

```bash
PYTHONPATH="/Users/steve/Documents/Bewerber_Assistent/bewerber/src" python3 -m bewerber.cli tailor \
  --rebuild "/Users/steve/Documents/Bewerbungsunterlagen/Bewerbungen/2026-06-12_FIRMA_ROLLE"
```

PDFs refreshed instantly, no LLM cost.

- [ ] **Step 5: Document the run**

Append to `bewerber/RUNLOG.md`:

```markdown
## 2026-06-12 — Plan C first tailoring against real posting
- Firma: <FIRMA>, Rolle: <ROLLE>
- Posting source: <url|file>
- Output: <path to Bewerbungsordner>
- Lebenslauf quality: <note>
- Anschreiben quality: <note>
- Edits made: <list>
- Time: ~<X> seconds end-to-end
```

```bash
cd /Users/steve/Documents/Bewerber_Assistent
git add bewerber/RUNLOG.md
git commit -m "docs: Plan C first real-world tailoring run log"
```

---

## Self-Review

**Spec coverage check (Subsystem 3: Tailoring from design doc):**

| Spec requirement | Task |
|------------------|------|
| `bewerber tailor` CLI accepts URL or file input | Task 11 |
| Snapshot job posting (HTML + PDF) via Playwright | Task 4 |
| LLM pass 1: filter/reorder Lebenslauf (no fabrication) | Task 5 |
| LLM pass 2: generate Anschreiben with German style | Task 6 |
| Few-shot examples from `anschreiben_examples/*.txt` | Task 6, 10 |
| Lebenslauf rendered as PDF via WeasyPrint + Jinja2 | Task 7, 9 |
| Anschreiben rendered as PDF | Task 8, 9 |
| Bewerbungsordner: `Bewerbungsunterlagen/Bewerbungen/<datum>_<firma>_<rolle>/` | Task 2, 10 |
| Posting snapshot moved into Bewerbungsordner | Task 10 |
| `posting_meta.yaml` with URL, firma, kontakt, date | Task 10 |
| Sources (HTML, MD) saved next to PDFs (editable) | Task 10 |
| `--rebuild` regenerates PDFs from edited HTML/MD without LLM | Task 12 |
| Audit log `tailoring_log.json` | Task 10 |
| Hidden projects (sichtbar_in_lebenslauf=false) excluded from prompt and output | Task 5, 9 |
| E2E test covers full pipeline | Task 13 |
| Smoke run against real data | Task 14 |

All Subsystem-3 spec items covered ✓

**Placeholder scan:** Searched for "TBD"/"TODO" — none found in code; one in `RUNLOG.md` template (the user fills it in).

**Type consistency:**
- `CustomizedResume`, `CustomBerufserfahrung`, `CustomProject`, `AnschreibenContent`, `JobPosting`, `TailorInput`, `TailorResult` — all consistent across tasks
- LLMClient.structured signature matches across all callers
- `MasterProfile` from Plan A imported throughout
- `Paths.bewerbungen`, `Paths.anschreiben_examples`, `Paths.master_profile` — all from Plan A's `paths.py`
- Slug functions: `slug_part` and `bewerbungsordner_name` used in Task 2 + 10
- `render_lebenslauf`, `render_anschreiben` signatures stable between Tasks 9, 10, 12

**Edge case considered and called out:** `--rebuild` test (Task 12) uses a stand-alone HTML file with no Jinja2 placeholders — this exercises the "user edited the HTML" path. If the file still contains Jinja2 tokens like `{{ profile.name }}`, WeasyPrint would render them literally. This is correct behavior: edit → rebuild → exact output.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-12-plan-c-tailoring.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
