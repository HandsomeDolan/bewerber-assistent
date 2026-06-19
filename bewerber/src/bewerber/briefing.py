"""Interview-Briefing-Generator.

Erstellt fuer eine Bewerbung (Status 'applied') ein vollstaendiges Interview-
Vorbereitungs-Dokument: Firmen-Uebersicht, Rollen-Erwartungen, Profil-Framing,
~7 zu erwartende Fragen mit redebereiten Antworten, Gegenfragen, Gehalts-
strategie, Sprechstil-Tipps.

Ein LLM-Call (Scoring-Chain, gpt-5-mini / gemini-2.5-flash) liefert die
strukturierten Inhalte; Jinja+WeasyPrint rendert daraus die PDF.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from bewerber.shared.llm import LLMClient
from bewerber.shared.state_schema import _ListOfStr


# ---------------------------------------------------------------------------
# Schema fuer LLM-Output
# ---------------------------------------------------------------------------

class ProfileFramingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anforderung: str = Field(description="Konkrete Anforderung aus der Ausschreibung")
    match_aus_profil: str = Field(description="Wie der Kandidat das aus seinem Profil belegen kann - konkrete Stationen/Projekte/Zahlen")


class QAEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frage: str = Field(description="Wahrscheinliche Interview-Frage")
    antwort: str = Field(description="Redebereit-formulierte Antwort, 80-150 Worte, im Sprechstil des Kandidaten, STAR-strukturiert wo moeglich, konkrete Zahlen aus seinem Profil")


class AskedQuestionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frage: str = Field(description="Frage die der Kandidat dem Arbeitgeber stellen sollte")
    warum: str = Field(description="Was der Kandidat damit zeigt oder lernt")


class InterviewBriefingContent(BaseModel):
    """Strukturierter LLM-Output fuer ein vollstaendiges Interview-Briefing."""
    model_config = ConfigDict(extra="forbid")

    company_overview: str = Field(
        description="2-3 Saetze ueber das Unternehmen - was machen sie, fuer wen, wie positioniert"
    )
    company_facts: _ListOfStr = Field(
        default_factory=list,
        description="5-8 Bullet-Points: Geschaeftsfeld, Gruender/CEO, Sitz, Mitarbeiterzahl, Tochterfirmen oder Marken, bekannte Produkte oder Studien",
    )
    methodik_und_tonalitaet: _ListOfStr = Field(
        default_factory=list,
        description="3-5 Punkte: typische Phrasen, Werte oder Methoden des Unternehmens aus dem Posting ableitbar - so klingen sie",
    )

    role_summary: str = Field(
        description="1 Absatz: was macht die Rolle konkret, welcher Projekttyp, welche Verantwortung"
    )
    role_does: _ListOfStr = Field(
        default_factory=list,
        description="Kernverantwortlichkeiten - was tut der Kandidat in dieser Rolle",
    )
    role_doesnt: _ListOfStr = Field(
        default_factory=list,
        description="Was die Rolle explizit NICHT umfasst (falls aus Posting ableitbar) - wichtig fuer realistische Erwartung",
    )

    profile_framing: list[ProfileFramingEntry] = Field(
        description="6-10 Eintraege: pro Anforderung der Stelle eine konkrete Belegstelle aus dem Master-Profil"
    )

    expected_questions: list[QAEntry] = Field(
        description="6-8 wahrscheinliche Interview-Fragen mit redebereiten Antworten. Mische klassische Opener ('Erzaehlen Sie von sich'), Motivation ('Warum diese Firma'), fachliche Fragen (zur Rolle passend), kompensatorische Fragen (Schwaeche/fehlende Erfahrung), Verhaltens-Fragen (Konflikt/Fehler)",
    )

    questions_to_ask: list[AskedQuestionEntry] = Field(
        description="5-7 Fragen die der Kandidat dem Arbeitgeber stellen sollte. Mischung aus inhaltlich (Projektkonstellation, Tools, Karriere-Pfad) und kommerziell (Pricing, Pre-Sales)",
    )

    salary_advice: str = Field(
        description="2-3 Saetze: realistische Range fuer die Rolle in Deutschland + konkrete Verhandlungs-Strategie (Wer-zuerst-nennt-verliert, Range vs. Punktzahl)",
    )

    closing_statement: str = Field(
        description="3-4 Saetze Vorschlag fuer ein Schlussstatement des Kandidaten - selbstbewusst aber nicht anbiedernd, mit Aufgreifen einer Spezifik des Unternehmens",
    )

    red_flags: _ListOfStr = Field(
        default_factory=list,
        description="2-5 kritische Punkte: was am Posting unklar oder potenziell problematisch ist, wo der Kandidat im Gespraech nachfragen sollte",
    )

    sprechstil_tips: _ListOfStr = Field(
        default_factory=list,
        description="3-5 Mini-Tipps fuer das Gespraech: Dresscode-Hinweis falls Posting Aufschluss gibt, Tonalitaet, konkrete Zahlen-Anker aus Profil nennen",
    )


# ---------------------------------------------------------------------------
# LLM-Call
# ---------------------------------------------------------------------------

BRIEFING_SYSTEM_PROMPT = """Du bist ein erfahrener deutscher Karriere-Coach. Du erstellst Interview-
Briefings fuer Bewerber, die zu einem Vorstellungsgespraech eingeladen wurden.

KRITISCHE REGELN:
1. Antworte ausschliesslich auf Deutsch.
2. Verwende AUSSCHLIESSLICH klassische Bindestriche (-). KEINE em-/en-dashes.
3. ALLE Antworten muessen aus dem MASTER-PROFIL belegbar sein - erfinde keine
   Stationen, Skills oder Zahlen, die nicht im Master stehen.
4. Bei den 'expected_questions': formuliere die Antworten redebereit aus, so dass
   der Kandidat sie im Gespraech in seinen eigenen Worten paraphrasieren kann.
   80-150 Worte pro Antwort. Nutze STAR-Struktur (Situation, Task, Action, Result)
   bei behavioralen Fragen. Wo immer moeglich: konkrete Zahlen aus seinem Profil
   einbauen (z.B. '1,5 h auf 10 min pro Tag').
5. Bei 'profile_framing': jeweils EINE konkrete Stelle/Projekt/Zahl aus dem Master
   nennen, nicht abstrakt.
6. Beim Schlussstatement: greife eine Spezifik des Arbeitgebers auf (z.B. Hybrid
   aus Foresight + KI, oder ungewoehnliche Branche, oder das was die Firma
   ausmacht), damit der Kandidat zeigt, dass er die Firma verstanden hat.
7. Bei den 'expected_questions' mische 3 Typen ungefaehr gleich:
   - 1-2x Opener / Motivation (Erzaehlen Sie sich; Warum diese Firma)
   - 2-3x fachliche / methodische (zur konkreten Rolle passend - z.B. Use-Case-
     Priorisierung, Tool-Wahl, Stakeholder-Umgang)
   - 1-2x kompensatorisch / behavioral (fehlende Erfahrung; Schwaeche; Konflikt)
8. Wenn die Stellenausschreibung explizit Dinge ausschliesst (z.B. 'ohne selbst
   zu entwickeln', 'kein Coding'), nimm das in 'role_doesnt' auf und betone in
   'sprechstil_tips' dass der Kandidat sich nicht als Implementierer positionieren
   soll.

QUALITAETSANSPRUCH: Das Briefing ersetzt einen 30-minuetigen Coaching-Termin.
Wenn der Kandidat es vorab durchliest, weiss er, wie er sich positioniert,
welche Fragen kommen werden und wie er antwortet."""


def generate_briefing(
    posting_text: str,
    master_yaml_text: str,
    firma: str,
    rolle: str,
    *,
    matched_skills: Optional[list[str]] = None,
    missing_skills: Optional[list[str]] = None,
    red_flags_aus_scoring: Optional[list[str]] = None,
    llm: LLMClient,
) -> InterviewBriefingContent:
    """Ein LLM-Call: erzeugt das gesamte Briefing als strukturiertes Objekt.

    Args:
        posting_text: Volltext der Stellenausschreibung
        master_yaml_text: Master-Profil als YAML-String
        firma: Firmenname (fuer den System-Kontext)
        rolle: Rollenbezeichnung
        matched_skills: Falls Scoring vorhanden, ueber-erfuelle Skills
        missing_skills: Falls Scoring vorhanden, Gaps
        red_flags_aus_scoring: Vom Scoring bereits identifizierte Knackpunkte
    """
    scoring_context = ""
    if matched_skills:
        scoring_context += f"\n\nBEREITS ERKANNTE MATCHED SKILLS: {', '.join(matched_skills)}"
    if missing_skills:
        scoring_context += f"\n\nBEREITS ERKANNTE GAPS: {', '.join(missing_skills)}"
    if red_flags_aus_scoring:
        scoring_context += f"\n\nBEREITS ERKANNTE RED FLAGS: {', '.join(red_flags_aus_scoring)}"

    user = (
        "MASTER-PROFIL DES KANDIDATEN:\n"
        f"{master_yaml_text}\n\n"
        "STELLENAUSSCHREIBUNG:\n"
        f"Firma: {firma}\n"
        f"Rolle: {rolle}\n\n"
        f"{posting_text}"
        f"{scoring_context}\n\n"
        "Erstelle ein vollstaendiges Interview-Briefing nach dem Schema."
    )
    return llm.structured(
        system=BRIEFING_SYSTEM_PROMPT,
        user=user,
        schema=InterviewBriefingContent,
    )
