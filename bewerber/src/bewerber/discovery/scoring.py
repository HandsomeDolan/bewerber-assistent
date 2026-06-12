from bewerber.shared.llm import LLMClient
from bewerber.shared.state_schema import RawJob, Scoring


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
