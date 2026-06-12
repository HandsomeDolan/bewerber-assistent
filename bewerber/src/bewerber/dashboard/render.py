import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bewerber.shared.state_schema import BewerberState


TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"


def render_dashboard(state: BewerberState) -> str:
    """Render the static dashboard HTML from a BewerberState."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("dashboard.html.j2")
    data_json = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
    return tpl.render(state=state, data_json=data_json)
