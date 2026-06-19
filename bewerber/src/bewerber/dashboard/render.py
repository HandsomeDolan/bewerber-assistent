import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bewerber.discovery.searches import SearchesConfig
from bewerber.shared.anlagen import AnlagenConfig
from bewerber.shared.paths import Paths
from bewerber.shared.state_schema import BewerberState


TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_dashboard(state: BewerberState, *, current_user: str | None = None) -> str:
    """Render the static dashboard HTML from a BewerberState."""
    tpl = _env().get_template("dashboard.html.j2")
    data_json = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
    workspace_path = str(Paths().workspace)
    return tpl.render(
        state=state,
        data_json=data_json,
        workspace_path=workspace_path,
        current_user=current_user,
    )


def render_login() -> str:
    """Render the /login page."""
    return _env().get_template("login.html.j2").render()


def render_onboarding(*, current_user: str | None = None) -> str:
    """Render the /onboarding stub (Phase 1: Platzhalter, Wizard kommt in Phase 2)."""
    return _env().get_template("onboarding.html.j2").render(current_user=current_user)


def render_interview_briefing(
    briefing,
    *,
    firma: str,
    rolle: str,
    generated_at: str,
    kandidat_name: str | None = None,
) -> str:
    """Render the LLM-generated InterviewBriefingContent as HTML."""
    tpl = _env().get_template("interview_briefing.html.j2")
    return tpl.render(
        b=briefing,
        firma=firma,
        rolle=rolle,
        firma_for_footer=firma[:50],
        rolle_for_footer=rolle[:50],
        generated_at=generated_at,
        kandidat_name=kandidat_name,
    )


def render_searches_editor(config: SearchesConfig) -> str:
    """Render the standalone /searches editor page."""
    tpl = _env().get_template("searches.html.j2")
    config_json = json.dumps(config.model_dump(), ensure_ascii=False)
    return tpl.render(config_json=config_json)


def render_anlagen_editor(config: AnlagenConfig) -> str:
    """Render the standalone /anlagen editor page."""
    tpl = _env().get_template("anlagen.html.j2")
    # Path objects need string serialization for the JSON embed
    cfg_dict = config.model_dump(mode="json")
    config_json = json.dumps(cfg_dict, ensure_ascii=False)
    return tpl.render(config_json=config_json)
