import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml

from bewerber.shared.llm import LLMClient
from bewerber.shared.paths import Paths
from bewerber.shared.profile_schema import MasterProfile
from bewerber.shared.slug import bewerbungsordner_name
from bewerber.tailoring.anschreiben import (
    AnschreibenContent,
    generate_anschreiben,
    _collect_few_shot_examples,
)
from bewerber.tailoring.customize import CustomizedResume, customize_resume
from bewerber.tailoring.render import render_anschreiben, render_lebenslauf


@dataclass
class TailorInput:
    posting_text: str
    firma: str
    rolle: str
    datum: str  # YYYY-MM-DD
    kontakt_name: Optional[str]
    source_url: Optional[str]
    snapshot_dir: Optional[Path]  # if URL was snapshotted, location of posting.html/pdf
    llm: LLMClient


@dataclass
class TailorResult:
    output_dir: Path
    lebenslauf_pdf: Path
    anschreiben_pdf: Path
    customized: CustomizedResume
    anschreiben: AnschreibenContent


def tailor(inp: TailorInput) -> TailorResult:
    """Run full tailoring pipeline: customize, anschreiben, render, save."""
    paths = Paths()
    master = _load_master(paths.master_profile)
    master_yaml_text = paths.master_profile.read_text(encoding="utf-8")

    customized = customize_resume(master, inp.posting_text, llm=inp.llm)
    few_shot = _collect_few_shot_examples(paths.anschreiben_examples)
    anschreiben = generate_anschreiben(
        master_yaml_text=master_yaml_text,
        job_description=inp.posting_text,
        kontakt_name=inp.kontakt_name,
        few_shot_examples=few_shot,
        llm=inp.llm,
    )

    out_dir = paths.bewerbungen / bewerbungsordner_name(inp.datum, inp.firma, inp.rolle)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Render PDFs and persist sources
    datum_de = _to_german_date(inp.datum)
    lebenslauf_pdf = render_lebenslauf(master, customized)
    anschreiben_pdf = render_anschreiben(
        master, anschreiben,
        firma=inp.firma, rolle=inp.rolle, datum=datum_de, kontakt_name=inp.kontakt_name,
    )
    (out_dir / "lebenslauf.pdf").write_bytes(lebenslauf_pdf)
    (out_dir / "anschreiben.pdf").write_bytes(anschreiben_pdf)
    (out_dir / "lebenslauf.html").write_text(_lebenslauf_html(master, customized), encoding="utf-8")
    (out_dir / "anschreiben.md").write_text(anschreiben.to_markdown(), encoding="utf-8")
    (out_dir / "posting.txt").write_text(inp.posting_text, encoding="utf-8")

    # Move snapshot (posting.html/posting.pdf) into output dir if it was generated
    if inp.snapshot_dir is not None:
        for fname in ("posting.html", "posting.pdf"):
            src = inp.snapshot_dir / fname
            if src.is_file():
                shutil.move(str(src), str(out_dir / fname))

    # Posting metadata
    meta = {
        "firma": inp.firma,
        "rolle": inp.rolle,
        "datum": inp.datum,
        "kontakt_name": inp.kontakt_name,
        "source_url": inp.source_url,
    }
    (out_dir / "posting_meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # Audit log
    log = {
        "firma": inp.firma,
        "rolle": inp.rolle,
        "datum": inp.datum,
        "customized": customized.model_dump(),
        "anschreiben": anschreiben.model_dump(),
    }
    (out_dir / "tailoring_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return TailorResult(
        output_dir=out_dir,
        lebenslauf_pdf=out_dir / "lebenslauf.pdf",
        anschreiben_pdf=out_dir / "anschreiben.pdf",
        customized=customized,
        anschreiben=anschreiben,
    )


def _load_master(path: Path) -> MasterProfile:
    """Load and validate master_profile.yaml."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return MasterProfile(**data)


def _lebenslauf_html(master: MasterProfile, customized: CustomizedResume) -> str:
    """Render Lebenslauf HTML source (without PDF conversion) for later editing."""
    from bewerber.tailoring.render import _env, _select_highlighted_projects
    highlighted = _select_highlighted_projects(master, customized.projekte_hervorheben)
    return _env().get_template("lebenslauf.html.j2").render(
        profile=master, customized=customized, highlighted_projects=highlighted,
    )


def _to_german_date(iso: str) -> str:
    """`2026-06-12` → `12.06.2026`"""
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


from markdown_it import MarkdownIt
from weasyprint import HTML


def rebuild_pdfs(out_dir: Path) -> None:
    """Re-render Lebenslauf and Anschreiben PDFs from the edited HTML/MD sources.

    Reads `out_dir/lebenslauf.html` and `out_dir/anschreiben.md`. The Anschreiben
    markdown is rendered to a minimal HTML page (uses Anschreiben CSS from the
    original template).
    """
    lebenslauf_html_path = out_dir / "lebenslauf.html"
    anschreiben_md_path = out_dir / "anschreiben.md"

    if lebenslauf_html_path.is_file():
        html_text = lebenslauf_html_path.read_text(encoding="utf-8")
        (out_dir / "lebenslauf.pdf").write_bytes(HTML(string=html_text).write_pdf())

    if anschreiben_md_path.is_file():
        md_text = anschreiben_md_path.read_text(encoding="utf-8")
        body_html = MarkdownIt().render(md_text)
        full_html = _ANSCHREIBEN_REBUILD_TEMPLATE.format(body=body_html)
        (out_dir / "anschreiben.pdf").write_bytes(HTML(string=full_html).write_pdf())


_ANSCHREIBEN_REBUILD_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4; margin: 2.5cm 2.5cm 2cm 2.5cm; }}
body {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #222; }}
h1, h2, h3 {{ margin: 0.6em 0 0.4em 0; }}
p {{ margin: 0.6em 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
