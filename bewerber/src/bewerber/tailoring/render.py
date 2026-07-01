from typing import Optional
from weasyprint import HTML

from bewerber.shared.profile_schema import MasterProfile
from bewerber.tailoring.customize import CustomizedResume
from bewerber.tailoring.anschreiben import AnschreibenContent
from bewerber.tailoring.render_html import (
    _env, _labels, _extract_ort, _lebenslauf_html,
)


def render_lebenslauf(
    profile: MasterProfile,
    customized: CustomizedResume,
    zielposition_titel: Optional[str] = None,
    sprache: str = "de",
    template: str = "sets/classic/lebenslauf.html.j2",
    theme: dict | None = None,
) -> bytes:
    """Render Lebenslauf as PDF bytes."""
    html_text = _lebenslauf_html(profile, customized, zielposition_titel, sprache, template, theme=theme)
    return HTML(string=html_text).write_pdf()


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
    theme: dict | None = None,
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
        theme=theme,
    )
    return HTML(string=html_text).write_pdf()
