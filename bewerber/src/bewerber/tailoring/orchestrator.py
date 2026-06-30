import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml

from bewerber.shared.anlagen import copy_anlagen_to, load_anlagen
from bewerber.shared.llm import LLMClient
from bewerber.shared.paths import Paths
from bewerber.shared.profile_schema import MasterProfile
from bewerber.shared.slug import bewerbungsordner_name
from bewerber.shared.state import load_state, save_state
from bewerber.shared.state_schema import (
    BewerberState, JobStatus, RawJob, StatusHistoryEntry, TrackedJob,
)
from bewerber.tailoring.anschreiben import (
    AnschreibenContent,
    generate_anschreiben,
    _collect_few_shot_examples,
)
from bewerber.tailoring.customize import CustomizedResume, customize_resume
from bewerber.tailoring.render import render_anschreiben, render_lebenslauf, _lebenslauf_html
from bewerber.tailoring.templates_store import BuiltinTemplateStore, TemplateChoice


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
    paths: Paths
    starttermin: Optional[str] = None
    gehalt: Optional[str] = None
    sprache: str = "de"  # "de" | "en" - Sprache der erzeugten Bewerbung
    template: TemplateChoice = field(default_factory=TemplateChoice)


@dataclass
class TailorResult:
    output_dir: Path
    lebenslauf_pdf: Path
    anschreiben_pdf: Path
    customized: CustomizedResume
    anschreiben: AnschreibenContent


def tailor(inp: TailorInput) -> TailorResult:
    """Run full tailoring pipeline: customize, anschreiben, render, save."""
    paths = inp.paths
    master = _load_master(paths.master_profile)
    master_yaml_text = paths.master_profile.read_text(encoding="utf-8")

    customized = customize_resume(master, inp.posting_text, llm=inp.llm, sprache=inp.sprache)
    few_shot = _collect_few_shot_examples(paths.anschreiben_examples)
    anschreiben = generate_anschreiben(
        master_yaml_text=master_yaml_text,
        job_description=inp.posting_text,
        kontakt_name=inp.kontakt_name,
        few_shot_examples=few_shot,
        llm=inp.llm,
        starttermin=inp.starttermin,
        gehalt=inp.gehalt,
        sprache=inp.sprache,
    )

    out_dir = paths.bewerbungen / bewerbungsordner_name(inp.datum, inp.firma, inp.rolle)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load anlagen config (Zeugnisse etc.) so labels stay in sync with the
    # files that will end up in the Bewerbungsordner.
    anlagen_cfg = load_anlagen(paths.anlagen_yaml)
    anlagen_liste = ["Lebenslauf"] + anlagen_cfg.labels

    # Render PDFs and persist sources
    store = BuiltinTemplateStore()
    cv_tpl = store.template_path(inp.template.cv(), "lebenslauf")
    ans_tpl = store.template_path(inp.template.anschreiben(), "anschreiben")

    datum_fmt = _format_date(inp.datum, inp.sprache)
    lebenslauf_pdf = render_lebenslauf(master, customized, zielposition_titel=inp.rolle,
                                       sprache=inp.sprache, template=cv_tpl)
    anschreiben_pdf = render_anschreiben(
        master, anschreiben,
        firma=inp.firma, rolle=inp.rolle, datum=datum_fmt, kontakt_name=inp.kontakt_name,
        anlagen=anlagen_liste, sprache=inp.sprache, template=ans_tpl,
    )
    (out_dir / "lebenslauf.pdf").write_bytes(lebenslauf_pdf)
    (out_dir / "anschreiben.pdf").write_bytes(anschreiben_pdf)
    (out_dir / "lebenslauf.html").write_text(
        _lebenslauf_html(master, customized, zielposition_titel=inp.rolle,
                         sprache=inp.sprache, template=cv_tpl),
        encoding="utf-8",
    )
    (out_dir / "anschreiben.md").write_text(anschreiben.to_markdown(), encoding="utf-8")
    (out_dir / "posting.txt").write_text(inp.posting_text, encoding="utf-8")

    # Move snapshot (posting.html/posting.pdf) into output dir if it was generated
    if inp.snapshot_dir is not None:
        for fname in ("posting.html", "posting.pdf"):
            src = inp.snapshot_dir / fname
            if src.is_file():
                shutil.move(str(src), str(out_dir / fname))

    # Copy attachments (Zeugnisse etc.) from anlagen.yaml
    missing_anlagen = copy_anlagen_to(anlagen_cfg, out_dir, base_dir=paths.data_dir)

    # Posting metadata
    meta = {
        "firma": inp.firma,
        "rolle": inp.rolle,
        "datum": inp.datum,
        "kontakt_name": inp.kontakt_name,
        "source_url": inp.source_url,
        "starttermin": inp.starttermin,
        "gehalt": inp.gehalt,
        "anlagen": anlagen_liste,
        "missing_anlagen": missing_anlagen,
        "template_set": inp.template.set_id,
        "cv_set": inp.template.cv_set,
        "anschreiben_set": inp.template.anschreiben_set,
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

    _update_state_for_tailored(
        paths=paths,
        firma=inp.firma,
        rolle=inp.rolle,
        source_url=inp.source_url,
        tailored_dir=out_dir,
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


_EN_MONTHS = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]


def _format_date(iso: str, sprache: str = "de") -> str:
    """`2026-06-12` → `12.06.2026` (de) bzw. `June 12, 2026` (en)."""
    y, m, d = iso.split("-")
    if sprache == "en":
        return f"{_EN_MONTHS[int(m) - 1]} {int(d)}, {y}"
    return f"{d}.{m}.{y}"


# Backward-compatible alias
def _to_german_date(iso: str) -> str:
    return _format_date(iso, "de")


def _update_state_for_tailored(
    *,
    paths: Paths,
    firma: str,
    rolle: str,
    source_url: Optional[str],
    tailored_dir: Path,
) -> None:
    """Create or update a state.json entry for the just-tailored Bewerbung.

    Match strategy: if any existing TrackedJob has the same `raw.url` as source_url,
    update that job. Otherwise create a new manually-tracked job with board='manual'.
    """
    state = load_state(paths.state_json)

    matched_id: Optional[str] = None
    if source_url:
        for jid, job in state.jobs.items():
            if job.raw.url == source_url:
                matched_id = jid
                break

    now_iso = _now_iso_for_state()

    if matched_id is not None:
        existing = state.jobs[matched_id]
        existing.status = JobStatus.TAILORED
        existing.tailored_dir = str(tailored_dir)
        existing.status_history.append(StatusHistoryEntry(status=JobStatus.TAILORED, at=now_iso))
    else:
        external_id = (
            hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
            if source_url
            else hashlib.sha1(f"{firma}|{rolle}".encode("utf-8")).hexdigest()[:16]
        )
        new_id = f"manual-{external_id}"
        raw = RawJob(
            board="manual",
            external_id=external_id,
            url=source_url or "",
            title=rolle,
            company=firma,
            location="",
        )
        state.jobs[new_id] = TrackedJob(
            raw=raw,
            status=JobStatus.TAILORED,
            status_history=[StatusHistoryEntry(status=JobStatus.TAILORED, at=now_iso)],
            first_seen=now_iso,
            tailored_dir=str(tailored_dir),
        )

    save_state(paths.state_json, state)


def _now_iso_for_state() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


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
