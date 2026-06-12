from typing import Optional
import yaml
from pydantic import BaseModel, Field, ConfigDict

from bewerber.shared.llm import LLMClient
from bewerber.shared.profile_schema import MasterProfile


CUSTOMIZE_SYSTEM_PROMPT = """Du bist ein erfahrener deutscher Karriere-Coach. Du passt einen vorhandenen Lebenslauf
für eine spezifische Stellenausschreibung an, im Stil eines klassischen, monochromen deutschen Lebenslaufs.

KRITISCHE REGELN:
1. Erfinde KEINE Inhalte. Du darfst NUR aus den gegebenen Master-Profil-Daten zitieren oder umformulieren.
2. Wenn ein gefordertes Skill nicht im Master vorhanden ist, lass ihn weg - füge ihn nicht hinzu.
3. Du darfst Formulierungen anpassen, um Sprache auf die Ausschreibung auszurichten - Inhalt muss aber im Master stehen.
4. Antworte ausschließlich auf Deutsch.
5. Datumsangaben bleiben unverändert (YYYY-MM Format).
6. Verwende AUSSCHLIESSLICH klassische Bindestriche (-). KEINE em-dashes (—), KEINE en-dashes (–).

LEBENSLAUF-STRUKTUR (zwei getrennte Sektionen):

A) WERDEGANG (high-level Liste der Stellen)
   Pro Stelle: 4–6 prägnante Aufgaben-Bullets ohne Ergebnisse. Bei der aktuellen / jüngsten Stelle: high-level
   Verantwortungsbereiche (z. B. "Projektleitung", "Stakeholder-Management", "Architekturplanung"), KEINE
   Projektdetails.

B) DETAILLIERTE PROJEKTERFAHRUNG (thematisch gruppierte Detailblöcke pro Stelle)
   Pro Stelle bündele die Master-Inhalte zu 3–4 thematischen Blöcken (`projekterfahrung`). Jeder Block hat:
   - `titel`: einen ALLGEMEINEN, THEMATISCHEN Titel, NICHT Projektname/Ordnername. Beispiele:
       * statt "n8n Builder" → "Workflow-Automatisierung mit n8n & LLM-Integration"
       * statt "MerchApp" → "Mobile PWA für Bestands- und Verkaufsführung"
       * statt "16_Marketing" → "Marketing-Automation mit Klaviyo und Multi-Sprachen-Versand"
       * statt "BandScoring" → "Datengetriebene Scoring-Pipeline für Marktanalyse"
   - `aufgaben`: 3–6 Bullets, die die durchgeführten Tätigkeiten thematisch zusammenfassen
     (mehrere Master-Projekte dürfen in einem Block zusammengeführt werden)
   - `ergebnisse`: 1–4 konkrete Outcomes (Zahlen/Effekte) — Plain-Text-Aussagen ohne "→"-Präfix
     (das Präfix setzt das Template); priorisiere Aussagen mit Zahlen (z. B. "1,5 h/Tag → 10 min/Tag")

Bei Stellen, die im Master bereits konkrete `erfolge` haben (Magna, Hock Sachsen): nutze diese
direkt in den Ergebnis-Listen. Bei der aktuellen IC-Music-Stelle: leite Ergebnisse aus den
Projekt-`erfolge`-Listen ab.

SKILL-KATEGORISIERUNG (`skills_kategorisiert`):
Verteile die für die Stellenausschreibung relevantesten Skills aus dem Master auf folgende Kategorien:
- `prozessmanagement`: Prozessanalyse, KVP, REFA, KPI-Monitoring, Prozessdokumentation, Change-Management …
- `projektmanagement`: Projektplanung, Stakeholder-Management, Risikomanagement, Termin-/Budgetkontrolle …
- `kommunikation_training`: Workshop-Moderation, Mitarbeiterschulung, Coaching, Präsentation …
- `automatisierung_ki`: n8n, Supabase, Python, JavaScript, OpenAI, Apps Script, Docker, etc.
- `vertrieb`: CRM, Preisstrategien, Datenanalyse-im-Vertrieb, Account-Management …
Pro Kategorie höchstens 6–8 Begriffe, sortiert nach Relevanz für die Stelle. Lass Kategorien leer,
wenn kein passender Skill im Master vorhanden ist.

BERUFSPROFIL:
`berufsprofil_zugespitzt`: 2–4 Sätze, neu formuliert, um Match zur Ausschreibung herzustellen.
"""


class ProjekterfahrungBlock(BaseModel):
    """Thematischer Detail-Block in der DETAILLIERTE-PROJEKTERFAHRUNG-Sektion."""
    model_config = ConfigDict(extra="forbid")
    titel: str = Field(
        description="Allgemeiner thematischer Titel (z. B. 'Workflow-Automatisierung mit n8n'). NICHT Projekt-/Ordnername."
    )
    aufgaben: list[str] = Field(
        default_factory=list,
        description="3–6 Bullets, die mehrere Projekte thematisch zusammenführen können.",
    )
    ergebnisse: list[str] = Field(
        default_factory=list,
        description="1–4 konkrete Outcomes/Zahlen — Plain-Text-Aussagen ohne '→'-Präfix.",
    )


class CustomBerufserfahrung(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: str
    firma: str
    von: str
    bis: Optional[str] = None
    standort: Optional[str] = None
    werdegang_bullets: list[str] = Field(
        default_factory=list,
        description="4–6 high-level Aufgaben-Bullets für die WERDEGANG-Sektion (ohne Ergebnisse).",
    )
    projekterfahrung: list[ProjekterfahrungBlock] = Field(
        default_factory=list,
        description="3–4 thematische Blöcke für die DETAILLIERTE-PROJEKTERFAHRUNG-Sektion. "
                    "Leer lassen wenn die Stelle keine separaten Detail-Bullets braucht.",
    )


class SkillKategorien(BaseModel):
    """Skills sortiert in die 5 Standard-Kategorien des Lebenslaufs."""
    model_config = ConfigDict(extra="forbid")
    prozessmanagement: list[str] = Field(default_factory=list)
    projektmanagement: list[str] = Field(default_factory=list)
    kommunikation_training: list[str] = Field(default_factory=list)
    automatisierung_ki: list[str] = Field(default_factory=list)
    vertrieb: list[str] = Field(default_factory=list)


class CustomizedResume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    berufsprofil_zugespitzt: str = Field(description="2–4 Sätze, auf Stelle ausgerichtet.")
    berufserfahrung: list[CustomBerufserfahrung] = Field(
        description="Berufsstationen mit Werdegang-Bullets + thematischen Projekterfahrungs-Blöcken.",
    )
    skills_kategorisiert: SkillKategorien = Field(
        description="Skills in 5 Standardkategorien für die SKILLS-Sektion.",
    )


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
        "Erstelle eine zugeschnittene Lebenslauf-Struktur mit WERDEGANG (high-level) "
        "und DETAILLIERTER PROJEKTERFAHRUNG (thematische Blöcke). Nur aus dem Master schöpfen."
    )
    return llm.structured(
        system=CUSTOMIZE_SYSTEM_PROMPT,
        user=user,
        schema=CustomizedResume,
    )
