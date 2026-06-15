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


def render_lebenslauf(
    profile: MasterProfile,
    customized: CustomizedResume,
    zielposition_titel: Optional[str] = None,
) -> bytes:
    """Render Lebenslauf as PDF bytes.

    `zielposition_titel`: optional Untertitel im Header (z. B. Rolle, auf die beworben wird).
    Default: "Projekt- und Prozessmanager" (im Template hartcodiert als Fallback).
    """
    html_text = _lebenslauf_html(profile, customized, zielposition_titel)
    return HTML(string=html_text).write_pdf()


def _lebenslauf_html(
    profile: MasterProfile,
    customized: CustomizedResume,
    zielposition_titel: Optional[str] = None,
) -> str:
    """Render Lebenslauf HTML string (used by orchestrator to persist editable source)."""
    return _env().get_template("lebenslauf.html.j2").render(
        profile=profile,
        customized=customized,
        zielposition_titel=zielposition_titel,
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
) -> bytes:
    """Render Anschreiben as PDF bytes."""
    html_text = _env().get_template("anschreiben.html.j2").render(
        profile=profile,
        anschreiben=anschreiben,
        firma=firma,
        rolle=rolle,
        datum=datum,
        kontakt_name=kontakt_name,
        ort=_extract_ort(profile.person.adresse),
        anlagen=anlagen or [],
    )
    return HTML(string=html_text).write_pdf()
