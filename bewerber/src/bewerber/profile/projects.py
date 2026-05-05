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
    """`8 n8n_builder` → `n8n Builder` (number stripped, underscores → spaces, alpha-only words capitalised)."""
    title = re.sub(r"^\d+\s+", "", folder_name)
    title = title.replace("_", " ")
    # Capitalise words that consist purely of letters (leave words with digits intact, e.g. "n8n")
    words = [w.capitalize() if w.isalpha() else w for w in title.split(" ")]
    return " ".join(words)


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
