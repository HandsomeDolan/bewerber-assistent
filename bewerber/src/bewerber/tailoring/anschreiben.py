from pathlib import Path
from typing import Optional
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
   - Schluss (2-4 Sätze: Einladung zum Gespräch, Vorgaben zu Starttermin/Gehalt natürlich einweben, höfliche Verabschiedung)
   - Gruss (Standard "Mit freundlichen Grüßen" + Name)

VORGABEN-EINWEBUNG (falls vom Nutzer angegeben):
- Frühester Starttermin: muss explizit im Schluss erwähnt werden, in natürlicher Formulierung
  (z. B. "Mein frühestmöglicher Eintrittstermin ist der ..." oder "Ich kann ab ... beginnen").
- Gehaltsvorstellung: nur erwähnen, wenn vom Nutzer angegeben. Format:
  "Meine Gehaltsvorstellung liegt bei ... brutto pro Jahr."
"""


class AnschreibenContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anrede: str = Field(description="Sehr geehrte Frau X / Herr Y / Damen und Herren,")
    einleitung: str = Field(description="1-2 Sätze: Bezug + Interesse")
    hauptteil: str = Field(description="3-5 Sätze, ggf. Absätze. Konkrete Erfolge aus Master.")
    schluss: str = Field(description="2-4 Sätze: ggf. Starttermin + Gehalt natürlich einweben, Einladung zum Gespräch")
    gruss: str = Field(description="z.B. 'Mit freundlichen Grüßen\\n<Vorname Nachname>'")

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
    starttermin: Optional[str] = None,
    gehalt: Optional[str] = None,
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
        else "Es gibt keinen konkreten Ansprechpartner - Anrede: 'Sehr geehrte Damen und Herren,'"
    )

    vorgaben_lines = []
    if starttermin:
        vorgaben_lines.append(f"- Frühester Starttermin: {starttermin} (muss im Schluss erwähnt werden)")
    if gehalt:
        vorgaben_lines.append(f"- Gehaltsvorstellung: {gehalt} (muss im Schluss als jährliches Bruttogehalt erwähnt werden)")
    vorgaben_block = ""
    if vorgaben_lines:
        vorgaben_block = "VORGABEN DES NUTZERS (im Schluss-Absatz einweben):\n" + "\n".join(vorgaben_lines) + "\n\n"

    user = (
        "MASTER-PROFIL DES BEWERBERS:\n"
        f"{master_yaml_text}\n\n"
        "STELLENAUSSCHREIBUNG:\n"
        f"{job_description}\n\n"
        f"{kontakt_hint}\n\n"
        f"{vorgaben_block}"
        f"{examples_block}"
        "Verfasse das deutsche Anschreiben."
    )
    return llm.structured(
        system=ANSCHREIBEN_SYSTEM_PROMPT,
        user=user,
        schema=AnschreibenContent,
    )
