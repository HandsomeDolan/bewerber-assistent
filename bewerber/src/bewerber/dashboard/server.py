"""Tiny HTTP server that serves the dashboard and exposes mutation endpoints.

Endpoints:
    GET  /                  -> rendered dashboard.html (live state)
    GET  /searches          -> rendered searches.html (editor UI)
    GET  /api/searches      -> current searches.yaml as JSON
    POST /api/searches      -> validate (SearchesConfig) + atomically rewrite searches.yaml
    GET  /anlagen           -> rendered anlagen.html (editor UI)
    GET  /api/anlagen       -> current anlagen.yaml as JSON
    POST /api/anlagen       -> validate (AnlagenConfig) + atomically rewrite anlagen.yaml
    POST /api/anlagen/verify -> body {paths: [...]} -> returns {missing: [...]}
    POST /api/add-posting   -> body {url, firma, rolle} -> Playwright-Snapshot +
                               Score gegen master_profile + upsert in state.json.
                               Synchron, ~10-15s. Returns {ok, job_id, fit_score}.
    POST /api/tailor        -> body {job_id, starttermin, gehalt?, kontakt_name?}
                               Triggert serverseitig den vollen Tailor-Lauf
                               (customize + anschreiben + PDF + Anlagen-Copy).
                               Synchron, ~30-60s. Returns {ok, output_dir}.
    POST /api/mark          -> body {job_id, status, application_link?, interview_at?}
                               updates state.json + status_history, returns {ok: true}
    POST /api/note          -> body {job_id, text}
                               appends a timestamped note, returns {ok: true}
    POST /api/open-folder   -> body {path}
                               opens the path in Finder (macOS `open`). Useful because
                               browsers refuse file:// navigation from http://localhost.

The server is single-threaded and uses stdlib only (http.server, socketserver).
Designed for personal local use; not hardened for multi-user / public exposure.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from bewerber.discovery.searches import SearchesConfig
from bewerber.shared.anlagen import AnlagenConfig, copy_anlagen_to, load_anlagen
from bewerber.shared.paths import Paths
from bewerber.shared.state import load_state, save_state
from bewerber.shared.state_schema import JobStatus, StatusHistoryEntry
from bewerber.dashboard.render import (
    render_anlagen_editor,
    render_dashboard,
    render_searches_editor,
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _open_folder_macos(path: str) -> bool:
    """Open a folder in Finder. Returns True on success."""
    try:
        subprocess.run(["open", path], check=True, timeout=5)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


class _Handler(BaseHTTPRequestHandler):
    paths: Paths  # injected by factory

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A003 - stdlib API
        # Suppress default stderr access log
        pass

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path in ("/", "/index.html"):
            state = load_state(self.paths.state_json)
            self._send_html(render_dashboard(state))
            return
        if self.path == "/searches":
            self._send_html(render_searches_editor(_load_searches_config(self.paths)))
            return
        if self.path == "/api/searches":
            cfg = _load_searches_config(self.paths)
            self._send_json(200, cfg.model_dump())
            return
        if self.path == "/anlagen":
            self._send_html(render_anlagen_editor(load_anlagen(self.paths.anlagen_yaml)))
            return
        if self.path == "/api/anlagen":
            cfg = load_anlagen(self.paths.anlagen_yaml)
            self._send_json(200, cfg.model_dump(mode="json"))
            return
        self._send_json(404, {"error": "not found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        try:
            if self.path == "/api/mark":
                self._handle_mark()
            elif self.path == "/api/note":
                self._handle_note()
            elif self.path == "/api/open-folder":
                self._handle_open_folder()
            elif self.path == "/api/searches":
                self._handle_save_searches()
            elif self.path == "/api/anlagen":
                self._handle_save_anlagen()
            elif self.path == "/api/anlagen/verify":
                self._handle_verify_anlagen()
            elif self.path == "/api/add-posting":
                self._handle_add_posting()
            elif self.path == "/api/tailor":
                self._handle_tailor()
            else:
                self._send_json(404, {"error": "unknown endpoint"})
        except Exception as e:  # noqa: BLE001
            self._send_json(500, {"error": str(e)})

    def _handle_save_searches(self) -> None:
        body = self._read_json()
        try:
            cfg = SearchesConfig.model_validate(body)
        except ValidationError as ve:
            self._send_json(400, {"error": _format_validation_error(ve)})
            return
        _save_searches_atomic(self.paths.bewerber_dir / "searches.yaml", cfg)
        self._send_json(200, {"ok": True, "searches": len(cfg.searches)})

    def _handle_save_anlagen(self) -> None:
        body = self._read_json()
        try:
            cfg = AnlagenConfig.model_validate(body)
        except ValidationError as ve:
            self._send_json(400, {"error": _format_validation_error(ve)})
            return
        _save_anlagen_atomic(self.paths.anlagen_yaml, cfg)
        # Report missing files so UI can warn user, but save still succeeded
        missing = [
            str(f) for a in cfg.anlagen for f in a.files if not Path(f).is_file()
        ]
        self._send_json(200, {"ok": True, "anlagen": len(cfg.anlagen), "missing": missing})

    def _handle_verify_anlagen(self) -> None:
        body = self._read_json()
        paths = body.get("paths", [])
        if not isinstance(paths, list):
            self._send_json(400, {"error": "paths must be a list"})
            return
        missing = [p for p in paths if not Path(p).is_file()]
        self._send_json(200, {"missing": missing})

    def _handle_add_posting(self) -> None:
        """Manually add a job via URL: snapshot + score + upsert to state."""
        body = self._read_json()
        url = (body.get("url") or "").strip()
        firma = (body.get("firma") or "").strip()
        rolle = (body.get("rolle") or "").strip()
        if not url or not firma or not rolle:
            self._send_json(400, {"error": "url, firma und rolle sind erforderlich"})
            return

        state = load_state(self.paths.state_json)
        for jid, job in state.jobs.items():
            if job.raw.url == url:
                self._send_json(
                    409,
                    {"error": f"URL bereits erfasst als Job {jid!r}"},
                )
                return

        if not self.paths.master_profile.is_file():
            self._send_json(
                500,
                {"error": f"master_profile.yaml fehlt unter {self.paths.master_profile}"},
            )
            return

        # Lazy imports - snapshot pulls in Playwright (heavy)
        from bewerber.tailoring.snapshot import snapshot_url
        from bewerber.discovery.enrich import enrich_job
        from bewerber.discovery.scoring import score_job
        from bewerber.shared.llm import LLMClient
        from bewerber.shared.state import upsert_job
        from bewerber.shared.state_schema import RawJob, TrackedJob
        import hashlib
        import tempfile

        snap_dir = Path(tempfile.mkdtemp(prefix="bewerber-manual-"))
        try:
            posting_text = snapshot_url(url, snap_dir)
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": f"Snapshot fehlgeschlagen: {e}"})
            return

        external_id = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        job_id = f"manual-{external_id}"

        raw = RawJob(
            board="manual",
            external_id=external_id,
            url=url,
            title=rolle,
            company=firma,
            location="",
            description=posting_text,
        )
        enriched = enrich_job(raw)

        master_yaml_text = self.paths.master_profile.read_text(encoding="utf-8")
        llm = LLMClient.for_scoring()
        try:
            scoring = score_job(job=enriched, master_yaml_text=master_yaml_text, llm=llm)
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": f"Scoring fehlgeschlagen: {e}"})
            return

        tracked = TrackedJob(
            raw=enriched,
            scoring=scoring,
            first_seen=_now_iso(),
        )
        upsert_job(state, tracked)
        save_state(self.paths.state_json, state)

        self._send_json(200, {
            "ok": True,
            "job_id": job_id,
            "fit_score": scoring.fit_score,
        })

    def _handle_tailor(self) -> None:
        """Synchronously run the tailor pipeline for an existing job."""
        body = self._read_json()
        job_id = body.get("job_id")
        starttermin = (body.get("starttermin") or "").strip()
        if not job_id or not starttermin:
            self._send_json(400, {"error": "job_id und starttermin sind erforderlich"})
            return

        state = load_state(self.paths.state_json)
        job = state.jobs.get(job_id)
        if job is None:
            self._send_json(404, {"error": f"Job {job_id!r} nicht gefunden"})
            return

        from datetime import date
        from bewerber.shared.llm import LLMClient
        from bewerber.tailoring.orchestrator import TailorInput, tailor

        llm = LLMClient.for_generation()
        try:
            result = tailor(TailorInput(
                posting_text=job.raw.description or "",
                firma=job.raw.company,
                rolle=job.raw.title,
                datum=date.today().isoformat(),
                kontakt_name=body.get("kontakt_name") or None,
                source_url=job.raw.url or None,
                snapshot_dir=None,
                llm=llm,
                starttermin=starttermin,
                gehalt=body.get("gehalt") or None,
            ))
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": f"Tailor fehlgeschlagen: {e}"})
            return

        self._send_json(200, {
            "ok": True,
            "output_dir": str(result.output_dir),
        })

    def _handle_mark(self) -> None:
        body = self._read_json()
        job_id = body.get("job_id")
        status_str = body.get("status")
        if not job_id or not status_str:
            self._send_json(400, {"error": "job_id and status required"})
            return
        try:
            new_status = JobStatus(status_str)
        except ValueError:
            self._send_json(400, {"error": f"invalid status {status_str!r}"})
            return

        state = load_state(self.paths.state_json)
        job = state.jobs.get(job_id)
        if job is None:
            self._send_json(404, {"error": f"job {job_id!r} not found"})
            return

        job.status = new_status
        job.status_history.append(StatusHistoryEntry(status=new_status, at=_now_iso()))
        if body.get("application_link"):
            job.application_link = body["application_link"]
        if body.get("interview_at"):
            job.interview_scheduled = body["interview_at"]
        save_state(self.paths.state_json, state)
        self._send_json(200, {"ok": True, "job_id": job_id, "status": new_status.value})

    def _handle_note(self) -> None:
        body = self._read_json()
        job_id = body.get("job_id")
        text = body.get("text", "").strip()
        if not job_id or not text:
            self._send_json(400, {"error": "job_id and text required"})
            return

        state = load_state(self.paths.state_json)
        job = state.jobs.get(job_id)
        if job is None:
            self._send_json(404, {"error": f"job {job_id!r} not found"})
            return

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"[{stamp}] {text}"
        job.notes = f"{job.notes}\n{entry}".strip() if job.notes else entry
        save_state(self.paths.state_json, state)
        self._send_json(200, {"ok": True, "job_id": job_id})

    def _handle_open_folder(self) -> None:
        body = self._read_json()
        path = body.get("path", "").strip()
        if not path:
            self._send_json(400, {"error": "path required"})
            return
        if not Path(path).exists():
            self._send_json(404, {"error": f"path does not exist: {path}"})
            return
        ok = _open_folder_macos(path)
        self._send_json(200 if ok else 500, {"ok": ok})


def _load_searches_config(paths: Paths) -> SearchesConfig:
    """Load searches.yaml; return empty SearchesConfig when missing."""
    p = paths.bewerber_dir / "searches.yaml"
    if not p.is_file():
        return SearchesConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return SearchesConfig.model_validate(data)


def _save_searches_atomic(path: Path, cfg: SearchesConfig) -> None:
    """Atomically rewrite searches.yaml (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    yaml_text = yaml.safe_dump(
        cfg.model_dump(),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    tmp.write_text(yaml_text, encoding="utf-8")
    os.replace(tmp, path)


def _save_anlagen_atomic(path: Path, cfg: AnlagenConfig) -> None:
    """Atomically rewrite anlagen.yaml (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    yaml_text = yaml.safe_dump(
        cfg.model_dump(mode="json"),   # Path objects -> str
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    tmp.write_text(yaml_text, encoding="utf-8")
    os.replace(tmp, path)


def _format_validation_error(ve: ValidationError) -> str:
    """Render a pydantic ValidationError into a multi-line message for the UI."""
    lines = []
    for err in ve.errors():
        loc = ".".join(str(x) for x in err.get("loc", []))
        lines.append(f"{loc or '(root)'}: {err.get('msg', 'invalid')}")
    return "\n".join(lines)


def make_handler(paths: Paths) -> type[_Handler]:
    """Bind a Paths instance to a handler class (one fresh class per server)."""
    handler_cls = type("_BoundHandler", (_Handler,), {"paths": paths})
    return handler_cls


def serve(paths: Optional[Paths] = None, port: int = 0) -> HTTPServer:
    """Create and return a configured HTTPServer.

    `port=0` requests an ephemeral port. The caller is responsible for calling
    `serve_forever()` and `shutdown()`. Returned server has `server_address`
    available with the actual port.
    """
    paths = paths or Paths()
    handler = make_handler(paths)
    return HTTPServer(("127.0.0.1", port), handler)
