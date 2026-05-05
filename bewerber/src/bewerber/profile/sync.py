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
