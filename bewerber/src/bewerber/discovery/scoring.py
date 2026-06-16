from pydantic import BaseModel, ConfigDict, Field

from bewerber.shared.llm import LLMClient
from bewerber.shared.state_schema import RawJob, Scoring


class BatchScoreResult(BaseModel):
    """Kombinierte Extraktion (Firma + Rolle) + Scoring fuer den Batch-Workflow.

    Damit braucht der Batch-Lauf NUR EINEN LLM-Call pro URL:
    keine zwei separaten Schritte 'Metadata extrahieren' + 'scoren'.
    """
    model_config = ConfigDict(extra="forbid")
    firma: str = Field(description="Aus dem Posting extrahierter Firmenname. Knapp, kein Tracker-Text.")
    rolle: str = Field(description="Aus dem Posting extrahierter Job-/Rollentitel.")
    scoring: Scoring


BATCH_SCORE_SYSTEM_PROMPT = """Du bist ein kritischer deutscher Karriere-Coach.
Du erhaeltst (1) ein Bewerber-Master-Profil und (2) den extrahierten Text einer
Stellenausschreibung. Liefere DREI Dinge in einem einzigen JSON:

A) firma   - der reine Firmenname (z.B. "BMW Group", "Stadt Leipzig", "Acme GmbH").
             Ohne Slogans, ohne Job-Board-Branding, ohne Tracking-Suffix.
B) rolle   - der reine Rollentitel (z.B. "AI Project Manager",
             "Senior Consultant Digitalisierung"). Klammern wie "(m/w/d)"
             duerfen drinbleiben, aber keine Standort-Anhaenge.
C) scoring - normales Scoring nach folgenden Regeln:

REGELN FUER scoring:
1. Antworte ausschliesslich auf Deutsch.
2. fit_score: 1 (kein Match) bis 10 (perfekter Match). Sei realistisch, nicht hoffnungsfroh.
3. Erfinde keine Skills, die nicht im Master-Profil stehen.
4. begruendung: 2-3 praegnante Saetze. Was passt, was passt nicht.
5. matched_skills: Skills aus dem Master, die im Posting gefordert werden.
6. missing_skills: Skills, die im Posting gefordert werden, aber nicht im Master stehen.
7. red_flags: Punkte, die gegen die Stelle sprechen (Vor-Ort-Zwang, Branche-Mismatch, etc.).
8. verbessern_in_anschreiben: Konkrete Aspekte, die im Anschreiben adressiert werden sollten.
9. Verwende AUSSCHLIESSLICH klassische Bindestriche (-). KEINE em-/en-dashes.

Wenn Firma oder Rolle nicht zuverlaessig zu erkennen sind, schreibe in das
jeweilige Feld den besten Schaetzwert mit einem Vermerk '(unsicher)' am Ende.
"""


SCORING_SYSTEM_PROMPT = """Du bist ein kritischer deutscher Karriere-Coach.
Du bewertest, wie gut eine Stellenausschreibung zum Bewerber-Profil passt.

REGELN:
1. Antworte ausschließlich auf Deutsch.
2. fit_score: 1 (kein Match) bis 10 (perfekter Match). Sei realistisch, nicht hoffnungsfroh.
3. Erfinde keine Skills, die nicht im Master-Profil stehen.
4. begruendung: 2-3 prägnante Sätze. Was passt, was passt nicht.
5. matched_skills: Skills aus dem Master, die im Posting gefordert werden.
6. missing_skills: Skills, die im Posting gefordert werden, aber nicht im Master stehen.
7. red_flags: Punkte, die gegen die Stelle sprechen (Vor-Ort-Zwang, Branche-Mismatch, etc.).
8. verbessern_in_anschreiben: Konkrete Aspekte, die im Anschreiben adressiert werden sollten.
9. Verwende AUSSCHLIESSLICH klassische Bindestriche (-). KEINE em-/en-dashes.
"""


def extract_and_score(
    posting_text: str, master_yaml_text: str, llm: LLMClient
) -> BatchScoreResult:
    """Einziger LLM-Call: extrahiert Firma+Rolle aus dem Posting und scort gegen Master."""
    user = (
        "BEWERBER-PROFIL:\n"
        f"{master_yaml_text}\n\n"
        "STELLENAUSSCHREIBUNG (vollstaendiger Text):\n"
        f"{posting_text}\n\n"
        "Extrahiere firma + rolle aus dem Text und bewerte das Match."
    )
    return llm.structured(
        system=BATCH_SCORE_SYSTEM_PROMPT,
        user=user,
        schema=BatchScoreResult,
    )


def score_job(job: RawJob, master_yaml_text: str, llm: LLMClient) -> Scoring:
    description = job.description or "(keine ausführliche Beschreibung verfügbar)"
    user = (
        "BEWERBER-PROFIL:\n"
        f"{master_yaml_text}\n\n"
        "STELLENAUSSCHREIBUNG:\n"
        f"Titel: {job.title}\n"
        f"Firma: {job.company}\n"
        f"Ort:   {job.location}\n"
        f"URL:   {job.url}\n\n"
        f"Beschreibung:\n{description}\n\n"
        "Bewerte das Match."
    )
    return llm.structured(
        system=SCORING_SYSTEM_PROMPT,
        user=user,
        schema=Scoring,
    )
