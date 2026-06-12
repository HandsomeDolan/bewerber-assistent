from pathlib import Path
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


def render_lebenslauf(profile: MasterProfile, customized: CustomizedResume) -> bytes:
    """Render Lebenslauf as PDF bytes."""
    highlighted = _select_highlighted_projects(profile, customized.projekte_hervorheben)
    html_text = _env().get_template("lebenslauf.html.j2").render(
        profile=profile,
        customized=customized,
        highlighted_projects=highlighted,
    )
    return HTML(string=html_text).write_pdf()


def render_anschreiben(
    profile: MasterProfile,
    anschreiben: AnschreibenContent,
    firma: str,
    rolle: str,
    datum: str,
    kontakt_name: str | None,
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


def _select_highlighted_projects(profile: MasterProfile, ids: list[str]) -> list:
    """Return projekte from profile matching ids, in given order."""
    by_id = {p.id: p for p in profile.projekte if p.sichtbar_in_lebenslauf}
    out = []
    for pid in ids:
        if pid in by_id:
            out.append(by_id[pid])
    return out
