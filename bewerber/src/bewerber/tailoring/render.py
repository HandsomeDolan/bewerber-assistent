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


def render_anschreiben(
    profile: MasterProfile,
    anschreiben: AnschreibenContent,
    firma: str,
    rolle: str,
    datum: str,
    kontakt_name: Optional[str],
) -> bytes:
    """Render Anschreiben as PDF bytes."""
    html_text = _env().get_template("anschreiben.html.j2").render(
        profile=profile,
        anschreiben=anschreiben,
        firma=firma,
        rolle=rolle,
        datum=datum,
        kontakt_name=kontakt_name,
    )
    return HTML(string=html_text).write_pdf()
