from pathlib import Path
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from bewerber.shared.profile_schema import MasterProfile
from bewerber.tailoring.customize import CustomizedResume
from bewerber.tailoring.anschreiben import AnschreibenContent


TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )


# Statische Beschriftungen fuer CV + Anschreiben, sprachabhaengig. Die LLM-Texte
# (Profil, Bullets, Anrede, Gruss) kommen separat in der Zielsprache.
_LABELS = {
    "de": {
        "profil": "PROFIL", "skills": "SKILLS", "werdegang": "WERDEGANG",
        "projekte": "DETAILLIERTE PROJEKTERFAHRUNG", "bildung": "BILDUNG",
        "sprachen": "SPRACHEN", "zertifikate": "WEITERBILDUNGEN & ZERTIFIKATE",
        "sk_prozess": "Prozessmanagement", "sk_projekt": "Projektmanagement",
        "sk_komm": "Kommunikation & Training", "sk_auto": "Automatisierung & KI",
        "sk_vertrieb": "Vertrieb", "heute": "heute", "ergebnis": "Ergebnis",
        "zhd": "z. Hd.", "betreff_prefix": "Bewerbung als",
        "gruss_fallback": "Mit freundlichen Grüßen", "anlagen_titel": "Anlagen",
    },
    "en": {
        "profil": "PROFILE", "skills": "SKILLS", "werdegang": "EXPERIENCE",
        "projekte": "SELECTED PROJECT EXPERIENCE", "bildung": "EDUCATION",
        "sprachen": "LANGUAGES", "zertifikate": "TRAINING & CERTIFICATIONS",
        "sk_prozess": "Process Management", "sk_projekt": "Project Management",
        "sk_komm": "Communication & Training", "sk_auto": "Automation & AI",
        "sk_vertrieb": "Sales", "heute": "present", "ergebnis": "Result",
        "zhd": "Attn:", "betreff_prefix": "Application for",
        "gruss_fallback": "Kind regards", "anlagen_titel": "Enclosures",
    },
}


def _labels(sprache: str) -> dict:
    return _LABELS.get(sprache, _LABELS["de"])


def render_lebenslauf(
    profile: MasterProfile,
    customized: CustomizedResume,
    zielposition_titel: Optional[str] = None,
    sprache: str = "de",
    template: str = "sets/classic/lebenslauf.html.j2",
) -> bytes:
    """Render Lebenslauf as PDF bytes."""
    html_text = _lebenslauf_html(profile, customized, zielposition_titel, sprache, template)
    return HTML(string=html_text).write_pdf()


def _lebenslauf_html(
    profile: MasterProfile,
    customized: CustomizedResume,
    zielposition_titel: Optional[str] = None,
    sprache: str = "de",
    template: str = "sets/classic/lebenslauf.html.j2",
) -> str:
    return _env().get_template(template).render(
        profile=profile,
        customized=customized,
        zielposition_titel=zielposition_titel,
        lbl=_labels(sprache),
    )


def _extract_ort(adresse: Optional[str]) -> Optional[str]:
    """Best-effort: extract city from a freeform address string.

    Heuristic: split by comma, return the middle-ish part that looks like a city
    (not a house number, not a country). Falls back to None if uncertain.
    """
    if not adresse:
        return None
    parts = [p.strip() for p in adresse.split(",") if p.strip()]
    if not parts:
        return None
    # Drop the first part (typically "Strasse Hausnr") and last (country / postcode)
    candidates = parts[1:-1] if len(parts) >= 3 else parts[1:] if len(parts) == 2 else parts
    # Pick the first candidate that doesn't look like a Bundesland (single word that is not Berlin etc.)
    # Simple: just return the first candidate
    return candidates[0] if candidates else None


def render_anschreiben(
    profile: MasterProfile,
    anschreiben: AnschreibenContent,
    firma: str,
    rolle: str,
    datum: str,
    kontakt_name: Optional[str],
    anlagen: Optional[list[str]] = None,
    sprache: str = "de",
    template: str = "sets/classic/anschreiben.html.j2",
) -> bytes:
    """Render Anschreiben as PDF bytes."""
    html_text = _env().get_template(template).render(
        profile=profile,
        anschreiben=anschreiben,
        firma=firma,
        rolle=rolle,
        datum=datum,
        kontakt_name=kontakt_name,
        ort=_extract_ort(profile.person.adresse),
        anlagen=anlagen or [],
        lbl=_labels(sprache),
    )
    return HTML(string=html_text).write_pdf()
