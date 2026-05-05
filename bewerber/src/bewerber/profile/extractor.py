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
