from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict

from bewerber.shared.llm import LLMClient


ANSCHREIBEN_SYSTEM_PROMPT = """Du bist ein erfahrener deutscher Karriere-Coach. Du verfasst ein professionelles deutsches Anschreiben.

REGELN:
1. Erfinde keine Erfahrungen oder Skills. Nur aus dem gegebenen Master-Profil schöpfen.
2. Authentisch und konkret - keine Floskeln wie "highly motivated team player".
3. Direkter Bezug zur ausgeschriebenen Stelle: was du konkret mitbringst (aus Master) und warum genau diese Firma.
4. Stil: höflich, professionell, "Sie"-Form, aber persönlich und nicht hölzern.
5. Wenn Stil-Beispiele vorliegen: lerne den Ton/Aufbau daraus, kopiere aber nicht.
6. Verwende AUSSCHLIESSLICH klassische Bindestriche (-). KEINE em-dashes (—), KEINE en-dashes (–).
7. Vier inhaltliche Abschnitte ohne Zwischenüberschriften:
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
