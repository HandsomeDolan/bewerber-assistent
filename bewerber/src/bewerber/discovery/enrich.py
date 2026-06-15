import hashlib
import requests
from readability import Document
from typing import Optional
import re

from bewerber.shared.state_schema import RawJob


def _hash_description(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# Explizite Full-Remote-Signale (mit Quantifier oder Setting). Werden ZUERST
# getestet, damit "Vollstaendig remote moeglich" als remote (nicht hybrid)
# klassifiziert wird.
_REMOTE_PATTERNS = [
    r"\b(100\s?%|vollstaendig|vollständig|ausschliesslich|ausschließlich|komplett|fully)\s+remote\b",
    r"\bfull[- ]remote\b",
    r"\bremote[- ]first\b",
    r"\bremote[- ]only\b",
]
# Hybrid-Signale: "Homeoffice moeglich" / "remote moeglich" / "hybrid" etc.
# `\bhybrid\w*\b` deckt deutsche Deklination ab (hybride, hybridem, ...).
_HYBRID_PATTERNS = [
    r"\bhybrid\w*\b",
    r"home[- ]?office\s+(?:moeglich|moglich|möglich|anteilig|teilweise)",
    r"remote\s+(?:moeglich|moglich|möglich|anteilig|teilweise)",
    r"\bteilweise\s+remote\b",
    r"\banteilig\s+remote\b",
    r"mobiles\s+arbeiten\s+(?:moeglich|moglich|möglich)",
    r"\bmischmodell\b",
    r"\bflexibel\s+(?:zwischen|von)\s+home",
]
# Sehr generische Keywords ("remote", "home office") landen in einem
# Fallback-Pass NACH den expliziten Hybrid-Treffern -> sind nicht eindeutig
# vollremote, also lieber hybrid klassifizieren.
_AMBIGUOUS_FALLBACK_HYBRID = [
    r"\bremote\b",
    r"\bhome[- ]?office\b",
    r"\bhomeoffice\b",
]


def extract_arbeitsmodell(text: Optional[str]) -> Optional[str]:
    """Heuristik fuer "remote" / "hybrid"-Klassifikation aus Job-Beschreibung.

    Returns:
        "remote" bei explizitem 100% / Full-Remote-Versprechen,
        "hybrid" bei jedem anderen Hinweis auf flexible Arbeit (Default fuer
            mehrdeutige Faelle),
        None     wenn keinerlei Remote-/Home-Hinweis im Text.

    Keyword-basiert, kein LLM. False positives sind moeglich (z.B. wenn die
    Anzeige "wir bieten kein Homeoffice" sagt - hier wuerde "homeoffice"
    matchen). Akzeptables Risiko fuer die Anzeige-Funktion; bei Bedarf kann
    spaeter ein LLM-Pass dazwischen geschaltet werden.
    """
    if not text:
        return None
    low = text.lower()
    if any(re.search(p, low) for p in _REMOTE_PATTERNS):
        return "remote"
    if any(re.search(p, low) for p in _HYBRID_PATTERNS):
        return "hybrid"
    if any(re.search(p, low) for p in _AMBIGUOUS_FALLBACK_HYBRID):
        return "hybrid"
    return None


def extract_main_text(html: str) -> str:
    """Use readability to isolate main content, then strip remaining tags."""
    summary_html = Document(html).summary()
    # Strip tags + collapse whitespace
    text = re.sub(r"<[^>]+>", " ", summary_html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def enrich_job(job: RawJob, timeout: int = 20) -> RawJob:
    """Fetch the posting URL and populate description if not already present.
    Always re-runs the arbeitsmodell-Heuristik (kostenlos) auf der aktuellsten
    Beschreibung, damit auch bereits gescrapte Jobs nachtraeglich klassifiziert
    werden, wenn der Code spaeter ein neues Keyword lernt.

    On network failure: leave description as-is and return the job unchanged.
    """
    if job.description:
        # description already present - nur arbeitsmodell nachziehen falls leer
        if job.arbeitsmodell is None:
            mode = extract_arbeitsmodell(job.description)
            if mode:
                return job.model_copy(update={"arbeitsmodell": mode})
        return job

    try:
        resp = requests.get(
            job.url,
            headers={"User-Agent": "bewerber/0.1 (+https://github.com/)"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return job

    text = extract_main_text(resp.text)
    if not text:
        return job
    return job.model_copy(update={
        "description": text,
        "description_hash": _hash_description(text),
        "arbeitsmodell": extract_arbeitsmodell(text),
    })
