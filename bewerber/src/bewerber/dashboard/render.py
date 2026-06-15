import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bewerber.discovery.searches import SearchesConfig
from bewerber.shared.paths import Paths
from bewerber.shared.state_schema import BewerberState


TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_dashboard(state: BewerberState) -> str:
    """Render the static dashboard HTML from a BewerberState."""
    tpl = _env().get_template("dashboard.html.j2")
    data_json = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
    workspace_path = str(Paths().workspace)
    return tpl.render(state=state, data_json=data_json, workspace_path=workspace_path)


def render_searches_editor(config: SearchesConfig) -> str:
    """Render the standalone /searches editor page."""
    tpl = _env().get_template("searches.html.j2")
    config_json = json.dumps(config.model_dump(), ensure_ascii=False)
    return tpl.render(config_json=config_json)
