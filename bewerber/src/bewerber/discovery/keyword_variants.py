import logging
from pydantic import BaseModel, Field

from bewerber.shared.llm import LLMClient

log = logging.getLogger(__name__)

VARIANT_CATEGORIES = ("Übersetzung", "Schreibweise", "Synonym", "Senioritätsstufe")

_SYS = """Du hilfst bei der Job-Suche. Zu gegebenen Jobtiteln/Suchbegriffen (Seeds)
generierst du zusätzliche Keyword-Varianten, mit denen Job-Boards durchsucht werden.

Erzeuge Varianten in genau diesen Kategorien:
- "Übersetzung": deutsch <-> englisch (Projektmanager <-> Project Manager)
- "Schreibweise": Wortformen, Bindestriche, gängige Abkürzungen (Projektleitung, Projekt-Manager, PM)
- "Synonym": verwandte, real gebräuchliche Rollenbezeichnungen (Teamleiter, Programm-Manager)
- "Senioritätsstufe": Senior/Junior/Lead/Head of + Titel

Regeln:
- Nur realistische, auf Job-Boards tatsächlich gebräuchliche Titel.
- Wiederhole die Seeds NICHT.
- Jede Variante ist ein kurzer Suchbegriff (kein Satz, keine Erklärung).
- 'kategorie' MUSS exakt einer der vier Werte oben sein.
- Ist eine Beschreibung gegeben, richte die Varianten thematisch daran aus."""


class KeywordVariant(BaseModel):
    keyword: str
    kategorie: str


class KeywordVariants(BaseModel):
    variants: list[KeywordVariant] = Field(default_factory=list)


def _build_user_prompt(seeds: list[str], description: str) -> str:
    parts: list[str] = []
    if seeds:
        parts.append("Seeds (bestehende Suchbegriffe):\n" + "\n".join(f"- {s}" for s in seeds))
    if description:
        parts.append(f"Beschreibung, wonach gesucht wird:\n{description}")
    parts.append("Generiere passende zusätzliche Keyword-Varianten in den vier Kategorien.")
    return "\n\n".join(parts)


def _dedup(result: KeywordVariants, seeds: list[str]) -> KeywordVariants:
    seen = {s.strip().casefold() for s in seeds}
    out: list[KeywordVariant] = []
    for v in result.variants:
        kw = v.keyword.strip()
        key = kw.casefold()
        if not kw or key in seen:
            continue
        seen.add(key)
        out.append(KeywordVariant(keyword=kw, kategorie=v.kategorie))
    return KeywordVariants(variants=out)


def generate_keyword_variants(
    seeds: list[str], description: str, llm: LLMClient
) -> KeywordVariants:
    """Expandiert Seeds zu Keyword-Varianten (DE/EN, Schreibweisen, Synonyme,
    Senioritätsstufen). Dedupliziert gegen Seeds und interne Duplikate.
    Wirft ValueError, wenn weder Seeds noch Beschreibung vorliegen."""
    seeds_clean = [s.strip() for s in seeds if s and s.strip()]
    desc = (description or "").strip()
    if not seeds_clean and not desc:
        raise ValueError("Weder Seeds noch Beschreibung angegeben - nichts zu expandieren.")
    user = _build_user_prompt(seeds_clean, desc)
    result = llm.structured(system=_SYS, user=user, schema=KeywordVariants)
    return _dedup(result, seeds_clean)
