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
