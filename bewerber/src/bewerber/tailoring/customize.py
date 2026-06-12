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
