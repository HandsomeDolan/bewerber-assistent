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
    POST /api/batch-add-postings -> body {urls: [str, ...]}. Verarbeitet jede URL
                               sequenziell (snapshot + LLM-Call der Firma+Rolle
                               extrahiert UND scort). Streamt NDJSON-Events
                               (start/extracted/done/error) live an den Client.
                               Fehlgeschlagene URLs landen in state.failed_urls.
    POST /api/failed-urls/clear  -> loescht alle failed_urls.
    POST /api/failed-urls/remove -> body {url} -> loescht eine bestimmte URL.
    POST /api/tailor        -> body {job_id, starttermin, gehalt?, kontakt_name?}
                               Triggert serverseitig den vollen Tailor-Lauf
                               (customize + anschreiben + PDF + Anlagen-Copy).
                               Synchron, ~30-60s. Returns {ok, output_dir}.
    POST /api/batch-tailor  -> body {job_ids: [str, ...], starttermin, gehalt?}
                               Iteriert ueber alle job_ids, tailored jeden
                               einzeln mit dem GLEICHEN Starttermin (+Gehalt).
                               Kontakt-Name wird leer gelassen (zu spezifisch).
                               Streamt NDJSON-Events (start/done/error/skipped).
                               Bereits getailorde Jobs werden uebersprungen.
    POST /api/mark          -> body {job_id, status, application_link?, interview_at?}
                               updates state.json + status_history, returns {ok: true}
    POST /api/note          -> body {job_id, text}
                               appends a timestamped note, returns {ok: true}
    POST /api/notes-set     -> body {job_id, notes}
                               ueberschreibt notes-Feld komplett (freitext),
                               kein Timestamp. Returns {ok: true}.
    POST /api/open-folder   -> body {path}
                               opens the path in Finder (macOS `open`). Useful because
                               browsers refuse file:// navigation from http://localhost.

The server is single-threaded and uses stdlib only (http.server, socketserver).
Designed for personal local use; not hardened for multi-user / public exposure.
"""
from __future__ import annotations

import http.cookies
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import uuid
import urllib.parse
import zipfile
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
from bewerber.shared.theme_store import RESERVED
from bewerber.tailoring.templates_store import UserTemplateStore, TemplateChoice
from bewerber.shared.settings import load_settings, save_settings
from bewerber.dashboard import auth
from bewerber.dashboard.render import (
    render_anlagen_editor,
    render_dashboard,
    render_login,
    render_onboarding,
    render_searches_editor,
)


SESSION_COOKIE_NAME = "bewerber_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600   # 30 Tage


def _session_secret() -> str:
    return os.environ.get("BEWERBER_SECRET_KEY", "")


def _invite_code() -> str:
    return os.environ.get("BEWERBER_INVITE_CODE", "")


def _registry_path() -> Path:
    # users/registry.json liegt im geteilten Workspace (user-unabhaengig)
    return Paths().users_dir / "registry.json"

# ------------------------------------------------------------------
# Onboarding-Extraktion: Background-Thread-State (modul-level)
# ------------------------------------------------------------------
# Mapping job_id -> {"status": "running"|"done"|"failed",
#                    "result"?: {...}, "error"?: str, "started_at": iso}
# Lock fuer Schreiben (stdlib http.server ist single-threaded fuer Request-
# Handling, aber unsere Background-Threads schreiben parallel).
_onboarding_jobs: dict[str, dict] = {}
_onboarding_lock = threading.Lock()

_theme_jobs: dict[str, dict] = {}
_theme_lock = threading.Lock()

# Background-State fuer den manuellen Discover-Run vom Dashboard aus.
# Nur EIN Discover-Job zur Zeit (current_id). Wenn None: kein Lauf aktiv.
_discover_state: dict = {"current_id": None, "jobs": {}, "cancel_event": None}
_discover_lock = threading.Lock()

log = logging.getLogger(__name__)


def _parse_multipart(headers, body: bytes) -> dict[str, list[tuple[bytes, Optional[str]]]]:
    """Sehr fokussierter multipart/form-data-Parser auf reinem stdlib.

    Returns:  field_name -> list of (content_bytes, filename_or_None).
              filename ist None, wenn das Feld kein File-Upload war.

    Unterstuetzt das Browser-Standardformat. Keine Spezialfaelle wie
    Multipart-in-Multipart oder Content-Transfer-Encoding != 8bit.
    """
    ctype = headers.get("Content-Type", "")
    if "boundary=" not in ctype:
        return {}
    boundary = ctype.split("boundary=", 1)[1].split(";", 1)[0].strip()
    if boundary.startswith('"') and boundary.endswith('"'):
        boundary = boundary[1:-1]
    boundary_bytes = ("--" + boundary).encode()
    out: dict[str, list[tuple[bytes, Optional[str]]]] = {}
    for part in body.split(boundary_bytes):
        s = part.strip()
        if not s or s == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_block, content = part.split(b"\r\n\r\n", 1)
        if header_block.startswith(b"\r\n"):
            header_block = header_block[2:]
        if content.endswith(b"\r\n"):
            content = content[:-2]
        disposition = ""
        for line in header_block.decode("utf-8", errors="replace").split("\r\n"):
            if line.lower().startswith("content-disposition"):
                disposition = line
                break
        name: Optional[str] = None
        filename: Optional[str] = None
        for token in disposition.split(";"):
            token = token.strip()
            if token.startswith('name="') and token.endswith('"'):
                name = token[6:-1]
            elif token.startswith('filename="') and token.endswith('"'):
                filename = token[10:-1]
        if name:
            out.setdefault(name, []).append((content, filename))
    return out


def _run_discover_background(
    job_id: str, paths: Paths, cancel_event: threading.Event | None = None,
    per_board_limit: int = 15,
) -> None:
    """Background-Worker fuer den manuellen Discover-Lauf.

    progress -> Status-Dict (UI-Polling), checkpoint -> save_state nach jedem
    Board (Restart-sicher), cancel_event -> Abbruch via /api/discover/cancel.
    """
    started = datetime.now().isoformat(timespec="seconds")
    try:
        from bewerber.discovery.searches import load_searches
        from bewerber.discovery.orchestrator import discover
        from bewerber.shared.llm import LLMClient
        # Scrapper-Adapter laden (sonst leeres scraper_registry)
        from bewerber.discovery.scrapers import arbeitsagentur as _aa  # noqa: F401
        from bewerber.discovery.scrapers import linkedin as _li  # noqa: F401
        from bewerber.discovery.scrapers import indeed as _id  # noqa: F401

        searches_path = paths.searches_yaml
        if not searches_path.is_file():
            raise FileNotFoundError(f"searches.yaml fehlt: {searches_path}")
        config = load_searches(searches_path)
        if not config.searches:
            raise ValueError("searches.yaml hat keine Sucheintraege")

        master_yaml_text = paths.master_profile.read_text(encoding="utf-8")
        state = load_state(paths.state_json)
        jobs_before = len(state.jobs)
        llm = LLMClient.for_scoring()

        def _progress(p: dict) -> None:
            with _discover_lock:
                job = _discover_state["jobs"].get(job_id)
                if job is not None:
                    job["progress"] = p

        discover(
            config, state=state, master_yaml_text=master_yaml_text, llm=llm,
            progress=_progress,
            checkpoint=lambda st: save_state(paths.state_json, st),
            cancel=cancel_event,
            per_board_limit=per_board_limit,
        )
        save_state(paths.state_json, state)
        jobs_after = len(state.jobs)

        cancelled = cancel_event is not None and cancel_event.is_set()
        with _discover_lock:
            job = _discover_state["jobs"].setdefault(job_id, {})
            job.update({
                "status": "cancelled" if cancelled else "done",
                "started_at": started,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "new_jobs": jobs_after - jobs_before,
                "total_jobs": jobs_after,
                "scrape_errors": {b: e.last_error for b, e in state.scrape_errors.items()},
            })
            _discover_state["current_id"] = None
            _discover_state["cancel_event"] = None
    except Exception as e:  # noqa: BLE001 - background, log + report
        log.exception("[discover] %s failed", job_id)
        with _discover_lock:
            _discover_state["jobs"][job_id] = {
                "status": "failed",
                "started_at": started,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "error": str(e)[:500],
            }
            _discover_state["current_id"] = None
            _discover_state["cancel_event"] = None


def _run_onboarding_extraction(job_id: str, upload_dir: Path, paths: Paths) -> None:
    """Background-Worker: laeuft in eigenem Thread, schreibt master_profile.yaml am Ende."""
    started = datetime.now().isoformat(timespec="seconds")
    try:
        from bewerber.profile.extractor import extract_profile_from_documents
        from bewerber.shared.llm import LLMClient
        import yaml as _yaml

        llm = LLMClient.for_scoring()
        profile = extract_profile_from_documents(upload_dir, llm=llm)

        data = profile.model_dump(exclude_none=True)
        data["projekte"] = []  # erst spaeter via `bewerber projects scan` befuellt
        paths.bewerber_dir.mkdir(parents=True, exist_ok=True)
        paths.master_profile.write_text(
            _yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        summary = {
            "name": profile.person.name,
            "stellen": len(profile.berufserfahrung),
            "ausbildung": len(profile.ausbildung),
            "sprachen": len(profile.sprachen),
        }
        with _onboarding_lock:
            # update statt = neue dict: upload_dir + files bleiben fuer Step 4 erhalten
            _onboarding_jobs[job_id].update({
                "status": "done",
                "summary": summary,
                "master_profile_path": str(paths.master_profile),
            })
    except Exception as e:  # noqa: BLE001 - background, log + report-to-client
        log.exception("[onboarding] extraction %s failed", job_id)
        with _onboarding_lock:
            _onboarding_jobs[job_id].update({
                "status": "failed",
                "error": str(e)[:500],
            })


def _run_theme_extraction(job_id: str, file_path: Path, paths: Paths) -> None:
    """Background: leitet ein Theme aus dem Upload ab, haelt es als Entwurf."""
    try:
        from bewerber.tailoring.theme_extractor import extract_theme
        from bewerber.shared.llm import LLMClient
        theme = extract_theme(file_path, name="", llm=LLMClient.for_generation())
        with _theme_lock:
            _theme_jobs[job_id].update({"status": "done", "theme": theme.model_dump()})
    except Exception as e:  # noqa: BLE001
        log.exception("[theme] extraction %s failed", job_id)
        with _theme_lock:
            _theme_jobs[job_id].update({"status": "failed", "error": str(e)[:500]})
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _open_folder_macos(path: str) -> bool:
    """Open a folder in Finder. Returns True on success."""
    try:
        subprocess.run(["open", path], check=True, timeout=5)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


# Datei-Endungen, die NICHT zu den Bewerbungsunterlagen gehoeren (interne
# Quell-/Log-Dateien). Plus: alle "posting.*"-Dateien (die Job-Ausschreibung
# selbst) werden ausgeblendet.
_NON_DELIVERABLE_SUFFIXES = {".md", ".html", ".json", ".yaml"}


def _is_deliverable(rel_name: str) -> bool:
    """True, wenn die Datei in Download-ZIP/Datei-Liste gehoert.

    Reiner ANZEIGE-/Verpackungs-Filter (Datei-Liste + ZIP), KEINE
    Zugriffskontrolle: der Einzeldatei-Download (_handle_download) ist
    bewusst NICHT gefiltert - er ist pfad-validiert und nutzergebunden,
    erlaubt aber gezielt auch interne Dateien (z.B. posting.txt).
    """
    p = Path(rel_name)
    if p.suffix.lower() in _NON_DELIVERABLE_SUFFIXES:
        return False
    if p.stem.lower() == "posting":
        return False
    return True


_VALID_THEME_ID_RE = re.compile(r"[a-z0-9-]+")


def _valid_theme_id(tid: str) -> bool:
    """Theme-id muss ein lowercase-Slug sein (nur [a-z0-9-])."""
    return bool(_VALID_THEME_ID_RE.fullmatch(tid or ""))


def _build_template_choice(body: dict, paths) -> "TemplateChoice":
    """Baut TemplateChoice aus Request-Body; Default = User-Setting; validiert gegen Store."""
    store = UserTemplateStore(paths)
    default = load_settings(paths).default_template_set
    raw = (body.get("template_set") or default or "classic")
    set_id = raw if store.has_set(raw) else "classic"
    cv = body.get("cv_set") or None
    ans = body.get("anschreiben_set") or None
    cv = cv if (cv and store.has_set(cv)) else None
    ans = ans if (ans and store.has_set(ans)) else None
    return TemplateChoice(set_id=set_id, cv_set=cv, anschreiben_set=ans)


class _Handler(BaseHTTPRequestHandler):

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

    # ------------------------------------------------------------------
    # Session-Cookie + Routing-Helpers
    # ------------------------------------------------------------------

    def _session_user(self) -> Optional[str]:
        """Verifiziert das signierte bewerber_session-Cookie -> username oder None."""
        secret = _session_secret()
        if not secret:
            # Leerer HMAC-Key darf niemals eine gueltige Session liefern
            return None
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        try:
            cookies = http.cookies.SimpleCookie()
            cookies.load(raw)
            morsel = cookies.get(SESSION_COOKIE_NAME)
        except Exception:  # noqa: BLE001
            return None
        if morsel is None:
            return None
        value = urllib.parse.unquote(morsel.value).strip()
        username = auth.verify_session(value, secret)
        if username is None:
            return None
        # Signatur allein reicht nicht: geloeschte Accounts (oder Alt-Cookies
        # nach Registry-Reset) duerfen keine gueltige Session mehr haben.
        if username not in auth.load_registry(_registry_path()):
            return None
        return username

    def _set_session_cookie_header(self, username: str) -> None:
        """Set-Cookie mit signierter Session. VOR end_headers() rufen."""
        signed = auth.sign_session(username, _session_secret())
        quoted = urllib.parse.quote(signed)
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE_NAME}={quoted}; Max-Age={SESSION_MAX_AGE_SECONDS}; "
            f"Path=/; HttpOnly; SameSite=Lax",
        )

    @property
    def paths(self) -> "Paths":
        """Per-Request Paths, abgeleitet aus der verifizierten Session."""
        return Paths(user=self._session_user())

    def _require_session(self) -> Optional[str]:
        """Gibt username oder sendet 401 und gibt None zurueck (fuer API-Routen)."""
        user = self._session_user()
        if not user:
            self._send_json(401, {"error": "nicht eingeloggt"})
            return None
        return user

    def _current_display_name(self) -> Optional[str]:
        user = self._session_user()
        if not user:
            return None
        entry = auth.load_registry(_registry_path()).get(user, {})
        vn = entry.get("vorname", "")
        nn = entry.get("nachname", "")
        return f"{vn} {nn}".strip() or user

    def _clear_session_cookie_header(self) -> None:
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax",
        )

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

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
        # Querystring vom Pfad trennen, damit GET /api/foo?bar=baz matched
        parsed_path = urllib.parse.urlsplit(self.path).path
        if parsed_path == "/api/onboarding/status":
            self._handle_onboarding_status()
            return
        if parsed_path == "/api/themes/extract/status":
            self._handle_theme_extract_status()
            return
        if parsed_path == "/api/themes":
            self._handle_themes_list()
            return
        if parsed_path == "/api/themes/preview":
            self._handle_theme_preview()
            return
        if parsed_path == "/api/discover/status":
            self._handle_discover_status()
            return
        if parsed_path == "/api/job-files":
            self._handle_job_files(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
            return
        if parsed_path == "/api/download":
            self._handle_download(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
            return
        if parsed_path == "/api/download-zip":
            self._handle_download_zip(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
            return
        if parsed_path == "/api/templates":
            if self._require_session() is None:
                return
            store = UserTemplateStore(self.paths)
            sets = [s.model_dump() for s in store.list_sets()]
            self._send_json(200, {"sets": sets,
                                  "default": load_settings(self.paths).default_template_set})
            return
        if self.path in ("/", "/index.html"):
            session = self._session_user()
            if not session:
                self._redirect("/login")
                return
            if not self.paths.master_profile.is_file():
                self._redirect("/onboarding")
                return
            state = load_state(self.paths.state_json)
            self._send_html(render_dashboard(state, current_user=self._current_display_name()))
            return
        if self.path == "/login":
            self._send_html(render_login())
            return
        if self.path == "/onboarding":
            session = self._session_user()
            if not session:
                self._redirect("/login")
                return
            self._send_html(render_onboarding(current_user=self._current_display_name()))
            return
        if self.path == "/searches":
            if not self._session_user():
                self._redirect("/login")
                return
            self._send_html(render_searches_editor(_load_searches_config(self.paths)))
            return
        if self.path == "/api/searches":
            if self._require_session() is None:
                return
            cfg = _load_searches_config(self.paths)
            self._send_json(200, cfg.model_dump())
            return
        if self.path == "/anlagen":
            if not self._session_user():
                self._redirect("/login")
                return
            self._send_html(render_anlagen_editor(load_anlagen(self.paths.anlagen_yaml)))
            return
        if self.path == "/api/anlagen":
            if self._require_session() is None:
                return
            cfg = load_anlagen(self.paths.anlagen_yaml)
            self._send_json(200, cfg.model_dump(mode="json"))
            return
        self._send_json(404, {"error": "not found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        try:
            _OPEN_POST = {"/login", "/api/register", "/logout"}
            if self.path not in _OPEN_POST and self._require_session() is None:
                return
            if self.path == "/api/mark":
                self._handle_mark()
            elif self.path == "/api/note":
                self._handle_note()
            elif self.path == "/api/delete-job":
                self._handle_delete_job()
            elif self.path == "/api/open-folder":
                self._handle_open_folder()
            elif self.path == "/api/searches":
                self._handle_save_searches()
            elif self.path == "/api/anlagen":
                self._handle_save_anlagen()
            elif self.path == "/api/anlagen/verify":
                self._handle_verify_anlagen()
            elif self.path == "/api/anlagen/upload":
                self._handle_anlagen_upload()
            elif self.path == "/api/tailor":
                self._handle_tailor()
            elif self.path == "/api/notes-set":
                self._handle_notes_set()
            elif self.path == "/api/batch-add-postings":
                self._handle_batch_add()
                return  # streaming response already complete
            elif self.path == "/api/batch-tailor":
                self._handle_batch_tailor()
                return  # streaming response already complete
            elif self.path == "/api/failed-urls/clear":
                self._handle_failed_clear()
            elif self.path == "/api/failed-urls/remove":
                self._handle_failed_remove()
            elif self.path == "/login":
                self._handle_login()
            elif self.path == "/api/register":
                self._handle_register()
            elif self.path == "/logout":
                self._handle_logout()
            elif self.path == "/api/onboarding/extract":
                self._handle_onboarding_extract()
            elif self.path == "/api/themes":
                self._handle_theme_save()
            elif self.path == "/api/themes/extract":
                self._handle_theme_extract()
            elif self.path.startswith("/api/themes/") and self.path.endswith("/rename"):
                self._handle_theme_rename(self.path[len("/api/themes/"):-len("/rename")])
            elif self.path.startswith("/api/themes/") and self.path.endswith("/delete"):
                self._handle_theme_delete(self.path[len("/api/themes/"):-len("/delete")])
            elif self.path == "/api/onboarding/scan-folder":
                self._handle_onboarding_scan_folder()
            elif self.path == "/api/onboarding/save":
                self._handle_onboarding_save()
            elif self.path == "/api/briefing":
                self._handle_briefing()
            elif self.path == "/api/discover/run":
                self._handle_discover_run()
            elif self.path == "/api/discover/cancel":
                self._handle_discover_cancel()
            elif self.path == "/api/account/delete":
                self._handle_account_delete()
            elif self.path == "/api/settings/default-template":
                self._handle_set_default_template()
            elif self.path == "/api/keywords/generate":
                self._handle_generate_keywords()
            else:
                self._send_json(404, {"error": "unknown endpoint"})
        except Exception as e:  # noqa: BLE001
            self._send_json(500, {"error": str(e)})

    def _handle_generate_keywords(self) -> None:
        """POST /api/keywords/generate: body {seeds:[str], description:str}
        -> {variants:[{keyword,kategorie}]}. Synchroner LLM-Call."""
        body = self._read_json()
        seeds = body.get("seeds") or []
        description = body.get("description", "") or ""
        if not isinstance(seeds, list):
            self._send_json(400, {"error": "seeds muss eine Liste sein"})
            return

        from bewerber.shared.llm import (
            LLMClient,
            LLMQuotaExhausted,
            LLMTransientError,
            LLMAllProvidersFailed,
        )
        from bewerber.discovery.keyword_variants import generate_keyword_variants

        try:
            result = generate_keyword_variants(
                [str(s) for s in seeds], str(description), LLMClient.for_generation()
            )
        except ValueError:
            self._send_json(400, {
                "error": "Bitte gib zuerst Jobtitel/Suchbegriffe ein oder beschreibe, was du suchst."
            })
            return
        except (LLMQuotaExhausted, LLMTransientError, LLMAllProvidersFailed) as le:
            self._send_json(502, {"error": f"KI-Dienst nicht verfügbar: {le}"})
            return

        self._send_json(200, {"variants": [v.model_dump() for v in result.variants]})

    def _handle_save_searches(self) -> None:
        body = self._read_json()
        try:
            cfg = SearchesConfig.model_validate(body)
        except ValidationError as ve:
            self._send_json(400, {"error": _format_validation_error(ve)})
            return
        _save_searches_atomic(self.paths.searches_yaml, cfg)
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
        # Relative Pfade (z. B. "anlagen/zeugnis.pdf" aus dem Upload) gegen den
        # User-Workspace aufloesen - wie copy_anlagen_to() es beim Tailoring tut.
        base = self.paths.data_dir
        def _exists(raw: str) -> bool:
            pth = Path(raw)
            if not pth.is_absolute():
                pth = base / pth
            return pth.is_file()
        missing = [p for p in paths if not _exists(p)]
        self._send_json(200, {"missing": missing})

    def _handle_anlagen_upload(self) -> None:
        if self._require_session() is None:
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json(400, {"error": "Body fehlt"})
            return
        body = self.rfile.read(length)
        fields = _parse_multipart(self.headers, body)
        files = [(c, fn) for c, fn in fields.get("files", []) if fn and c]
        if not files:
            self._send_json(400, {"error": "Mindestens eine Datei erforderlich (Feld 'files')"})
            return
        anlagen_dir = self.paths.data_dir / "anlagen"
        anlagen_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for content, fname in files:
            safe = Path(fname or "upload").name
            (anlagen_dir / safe).write_bytes(content)
            saved.append(f"anlagen/{safe}")
        self._send_json(200, {"ok": True, "saved": saved})

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
                paths=self.paths,
                starttermin=starttermin,
                gehalt=body.get("gehalt") or None,
                sprache=body.get("sprache") or "de",
                template=_build_template_choice(body, self.paths),
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

    def _handle_delete_job(self) -> None:
        """Loescht einen Job aus state.json und (falls innerhalb des
        Bewerbungen-Ordners) das zugehoerige tailored_dir von der Platte."""
        body = self._read_json()
        job_id = body.get("job_id")
        if not job_id:
            self._send_json(400, {"error": "job_id required"})
            return

        state = load_state(self.paths.state_json)
        job = state.jobs.get(job_id)
        if job is None:
            self._send_json(404, {"error": f"job {job_id!r} not found"})
            return

        tailored_dir = job.tailored_dir
        del state.jobs[job_id]
        save_state(self.paths.state_json, state)

        dir_deleted = False
        if tailored_dir:
            td = Path(tailored_dir).resolve()
            base = self.paths.bewerbungen.resolve()
            # Nur loeschen, wenn td WIRKLICH unterhalb des Bewerbungen-Ordners liegt.
            if td.is_dir() and (td == base or str(td).startswith(str(base) + os.sep)):
                shutil.rmtree(td, ignore_errors=True)
                dir_deleted = not td.exists()

        self._send_json(200, {"ok": True, "job_id": job_id, "dir_deleted": dir_deleted})

    def _handle_batch_add(self) -> None:
        """Streaming-Endpoint: jede URL einzeln verarbeiten + Events live raussenden.

        Antwort-Format: NDJSON (eine JSON-Zeile pro Event), Content-Type
        application/x-ndjson, kein Content-Length -> Connection schliesst am Ende.
        """
        body = self._read_json()
        urls = body.get("urls", [])
        if not isinstance(urls, list) or not urls:
            self._send_json(400, {"error": "urls (Liste mit mind. 1 Eintrag) erforderlich"})
            return
        urls = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
        if not urls:
            self._send_json(400, {"error": "keine gueltigen URLs in der Liste"})
            return

        if not self.paths.master_profile.is_file():
            self._send_json(500, {"error": "master_profile.yaml fehlt"})
            return

        # Lazy imports (Playwright/LLM-stack ist heavy)
        from bewerber.tailoring.snapshot import snapshot_url
        from bewerber.discovery.enrich import enrich_job, extract_arbeitsmodell
        from bewerber.discovery.scoring import extract_and_score
        from bewerber.shared.llm import LLMClient
        from bewerber.shared.state import upsert_job
        from bewerber.shared.state_schema import FailedUrl, RawJob, TrackedJob
        import hashlib
        import tempfile

        # Streaming-Header senden
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def emit(event: dict) -> None:
            self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        master_yaml_text = self.paths.master_profile.read_text(encoding="utf-8")
        llm = LLMClient.for_scoring()
        total = len(urls)
        emit({"event": "begin", "total": total})

        for i, url in enumerate(urls):
            emit({"event": "start", "index": i, "url": url})
            try:
                state = load_state(self.paths.state_json)
                # Skip Duplikate
                if any(j.raw.url == url for j in state.jobs.values()):
                    emit({"event": "skipped_duplicate", "index": i, "url": url})
                    continue

                emit({"event": "phase", "index": i, "phase": "snapshot"})
                snap_dir = Path(tempfile.mkdtemp(prefix="bewerber-batch-"))
                posting_text = snapshot_url(url, snap_dir)

                emit({"event": "phase", "index": i, "phase": "llm"})
                result = extract_and_score(
                    posting_text=posting_text,
                    master_yaml_text=master_yaml_text,
                    llm=llm,
                )
                # Sobald die LLM den Rollennamen liefert, das UI updaten
                emit({
                    "event": "extracted", "index": i,
                    "firma": result.firma, "rolle": result.rolle,
                })

                external_id = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
                job_id = f"manual-{external_id}"
                raw = RawJob(
                    board="manual", external_id=external_id, url=url,
                    title=result.rolle, company=result.firma, location="",
                    description=posting_text,
                    arbeitsmodell=extract_arbeitsmodell(posting_text),
                )
                enriched = enrich_job(raw)
                tracked = TrackedJob(
                    raw=enriched,
                    scoring=result.scoring,
                    first_seen=_now_iso(),
                )
                upsert_job(state, tracked)
                # Falls die URL vorher in failed_urls war -> rausnehmen
                state.failed_urls = [f for f in state.failed_urls if f.url != url]
                save_state(self.paths.state_json, state)

                emit({
                    "event": "done", "index": i,
                    "job_id": job_id, "fit_score": result.scoring.fit_score,
                })
            except Exception as e:  # noqa: BLE001 - eine fehlerhafte URL stoppt nicht den Batch
                msg = str(e)[:300]
                emit({"event": "error", "index": i, "url": url, "error": msg})
                # In failed_urls persistieren
                try:
                    state = load_state(self.paths.state_json)
                    state.failed_urls = [f for f in state.failed_urls if f.url != url]
                    state.failed_urls.append(FailedUrl(url=url, error=msg, at=_now_iso()))
                    save_state(self.paths.state_json, state)
                except Exception:  # noqa: BLE001
                    pass

        emit({"event": "complete", "total": total})

    def _handle_onboarding_extract(self) -> None:
        """Receives PDFs via multipart, starts background extraction thread."""
        if not self._session_user():
            self._send_json(401, {"error": "Login erforderlich"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json(400, {"error": "Body fehlt"})
            return
        body = self.rfile.read(length)
        fields = _parse_multipart(self.headers, body)
        files = fields.get("files", [])
        files = [(c, fn) for c, fn in files if fn and c]
        if not files:
            self._send_json(400, {"error": "Mindestens eine Datei erforderlich (Form-Feld 'files')"})
            return

        # Files in temp-Dir ablegen
        import tempfile
        upload_dir = Path(tempfile.mkdtemp(prefix="bewerber-onboarding-"))
        saved = []
        for content, fname in files:
            safe = Path(fname or "upload").name
            target = upload_dir / safe
            target.write_bytes(content)
            saved.append(safe)

        # Background-Thread anstossen. upload_dir wird im Job-State behalten,
        # damit Step 4 (Anschreiben-Stil-Beispiele auswaehlen) die Originalfiles
        # noch findet, wenn der User nach erfolgreicher Extraktion "Finish" drueckt.
        job_id = str(uuid.uuid4())
        with _onboarding_lock:
            _onboarding_jobs[job_id] = {
                "status": "running",
                "started_at": _now_iso(),
                "files": saved,
                "upload_dir": str(upload_dir),
            }
        threading.Thread(
            target=_run_onboarding_extraction,
            args=(job_id, upload_dir, self.paths),
            daemon=True,
        ).start()

        self._send_json(200, {"ok": True, "job_id": job_id, "files": saved})

    def _handle_theme_extract(self) -> None:
        if self._require_session() is None:
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json(400, {"error": "Body fehlt"})
            return
        body = self.rfile.read(length)
        fields = _parse_multipart(self.headers, body)
        files = [(c, fn) for c, fn in fields.get("file", []) if fn and c]
        if not files:
            self._send_json(400, {"error": "Datei erforderlich (Form-Feld 'file')"})
            return
        content, fname = files[0]
        ext = Path(fname or "").suffix.lower()
        if ext not in (".pdf", ".docx"):
            self._send_json(400, {"error": "Nur PDF oder DOCX"})
            return
        import tempfile
        fd = Path(tempfile.mkdtemp(prefix="bewerber-theme-")) / ("upload" + ext)
        fd.write_bytes(content)
        job_id = str(uuid.uuid4())
        with _theme_lock:
            _theme_jobs[job_id] = {"status": "running", "started_at": _now_iso()}
        threading.Thread(target=_run_theme_extraction, args=(job_id, fd, self.paths), daemon=True).start()
        self._send_json(200, {"ok": True, "job_id": job_id})

    def _handle_theme_extract_status(self) -> None:
        if self._require_session() is None:
            return
        job_id = (urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("job_id") or [""])[0]
        with _theme_lock:
            job = _theme_jobs.get(job_id)
        if not job:
            self._send_json(404, {"error": "unbekannter job_id"})
            return
        self._send_json(200, job)

    def _handle_theme_save(self) -> None:
        if self._require_session() is None:
            return
        body = self._read_json()
        job_id = body.get("job_id"); name = (body.get("name") or "").strip()
        with _theme_lock:
            job = _theme_jobs.get(job_id)
        if not job or job.get("status") != "done" or "theme" not in job:
            self._send_json(400, {"error": "kein fertiger Theme-Entwurf zu job_id"})
            return
        from bewerber.shared.theme import Theme
        from bewerber.shared.theme_store import save_theme, list_themes, reserved_or_slug
        existing = {t.id for t in list_themes(self.paths)}
        slug = reserved_or_slug(name, existing)
        if slug is None:
            self._send_json(400, {"error": f"Name reserviert oder leer (nicht: {', '.join(sorted(RESERVED))})"})
            return
        theme = Theme.model_validate(job["theme"])
        theme.id = slug; theme.name = name
        save_theme(self.paths, theme)
        self._send_json(200, {"ok": True, "id": slug})

    def _handle_themes_list(self) -> None:
        if self._require_session() is None:
            return
        from bewerber.shared.theme_store import list_themes
        self._send_json(200, {"themes": [{"id": t.id, "name": t.name} for t in list_themes(self.paths)]})

    def _handle_theme_delete(self, theme_id: str) -> None:
        if not _valid_theme_id(theme_id):
            self._send_json(400, {"error": "ungueltige id"})
            return
        if self._require_session() is None:
            return
        from bewerber.shared.theme_store import delete_theme
        self._send_json(200, {"ok": True, "deleted": delete_theme(self.paths, theme_id)})

    def _handle_theme_rename(self, theme_id: str) -> None:
        if not _valid_theme_id(theme_id):
            self._send_json(400, {"error": "ungueltige id"})
            return
        if self._require_session() is None:
            return
        body = self._read_json(); name = (body.get("name") or "").strip()
        from bewerber.shared.theme_store import load_theme, save_theme
        t = load_theme(self.paths, theme_id)
        if t is None or not name:
            self._send_json(400, {"error": "Theme fehlt oder Name leer"})
            return
        t.name = name; save_theme(self.paths, t)
        self._send_json(200, {"ok": True, "id": theme_id, "name": name})

    def _handle_theme_preview(self) -> None:
        if self._require_session() is None:
            return
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        job_id = (q.get("job_id") or [""])[0]; theme_id = (q.get("id") or [""])[0]
        tokens = None
        if job_id:
            with _theme_lock:
                job = _theme_jobs.get(job_id)
            if job and job.get("theme"):
                from bewerber.shared.theme import Theme
                tokens = Theme.model_validate(job["theme"]).tokens()
        elif theme_id:
            if not _valid_theme_id(theme_id):
                self._send_json(400, {"error": "ungueltige id"})
                return
            from bewerber.shared.theme_store import load_theme
            t = load_theme(self.paths, theme_id)
            tokens = t.tokens() if t else None
        from bewerber.dashboard.sample_data import preview_html
        html = preview_html(tokens)
        self._send_html(html)

    def _handle_briefing(self) -> None:
        """Body: {job_id}. Generiert Interview-Briefing-PDF via LLM,
        legt sie unter <tailored_dir>/briefing/briefing_<datum>.pdf ab.
        Synchron (~30-60s).
        """
        if not self._session_user():
            self._send_json(401, {"error": "Login erforderlich"})
            return
        body = self._read_json()
        job_id = body.get("job_id")
        if not job_id:
            self._send_json(400, {"error": "job_id erforderlich"})
            return
        state = load_state(self.paths.state_json)
        job = state.jobs.get(job_id)
        if job is None:
            self._send_json(404, {"error": f"Job {job_id!r} nicht gefunden"})
            return
        if not job.tailored_dir:
            self._send_json(400, {"error": "Job hat keinen tailored_dir - erst Bewerbung erstellen"})
            return
        tailored_dir = Path(job.tailored_dir)
        if not tailored_dir.is_dir():
            self._send_json(400, {"error": f"tailored_dir existiert nicht: {tailored_dir}"})
            return
        if not self.paths.master_profile.is_file():
            self._send_json(500, {"error": "master_profile.yaml fehlt"})
            return

        from bewerber.briefing import generate_briefing
        from bewerber.shared.llm import LLMClient
        from bewerber.dashboard.render import render_interview_briefing
        from weasyprint import HTML

        try:
            master_yaml_text = self.paths.master_profile.read_text(encoding="utf-8")
            llm = LLMClient.for_scoring()
            scoring = job.scoring
            briefing = generate_briefing(
                posting_text=job.raw.description or "",
                master_yaml_text=master_yaml_text,
                firma=job.raw.company,
                rolle=job.raw.title,
                matched_skills=scoring.matched_skills if scoring else None,
                missing_skills=scoring.missing_skills if scoring else None,
                red_flags_aus_scoring=scoring.red_flags if scoring else None,
                llm=llm,
            )
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": f"LLM-Call fehlgeschlagen: {e}"})
            return

        # Kandidat-Name aus Master holen
        kandidat_name: Optional[str] = None
        try:
            import yaml as _yaml
            mp = _yaml.safe_load(master_yaml_text) or {}
            kandidat_name = (mp.get("person") or {}).get("name")
        except Exception:  # noqa: BLE001
            pass

        generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")
        html = render_interview_briefing(
            briefing,
            firma=job.raw.company,
            rolle=job.raw.title,
            generated_at=generated_at,
            kandidat_name=kandidat_name,
        )
        briefing_dir = tailored_dir / "briefing"
        briefing_dir.mkdir(parents=True, exist_ok=True)
        out_pdf = briefing_dir / f"briefing_{datetime.now().strftime('%Y-%m-%d_%H%M')}.pdf"
        HTML(string=html).write_pdf(str(out_pdf))

        self._send_json(200, {
            "ok": True,
            "pdf_path": str(out_pdf),
            "briefing_dir": str(briefing_dir),
        })

    def _handle_discover_run(self) -> None:
        """Startet einen Discover-Lauf im Hintergrund-Thread. Returnt sofort
        eine job_id; UI pollt /api/discover/status."""
        if not self._session_user():
            self._send_json(401, {"error": "Login erforderlich"})
            return
        body = self._read_json()
        limit = body.get("limit", 15)
        if not isinstance(limit, int) or not (1 <= limit <= 100):
            self._send_json(400, {
                "error": "limit muss eine Zahl zwischen 1 und 100 sein",
            })
            return
        with _discover_lock:
            if _discover_state["current_id"] is not None:
                self._send_json(409, {
                    "error": "Es laeuft bereits ein Discover-Run",
                    "current_job_id": _discover_state["current_id"],
                })
                return
            job_id = str(uuid.uuid4())
            cancel_event = threading.Event()
            _discover_state["jobs"][job_id] = {
                "status": "running",
                "started_at": _now_iso(),
            }
            _discover_state["current_id"] = job_id
            _discover_state["cancel_event"] = cancel_event
        threading.Thread(
            target=_run_discover_background,
            args=(job_id, self.paths, cancel_event, limit),
            daemon=True,
        ).start()
        self._send_json(200, {"ok": True, "job_id": job_id})

    def _handle_discover_cancel(self) -> None:
        """Bricht den laufenden Discover-Run ab (Stopp vor dem naechsten Job)."""
        if not self._session_user():
            self._send_json(401, {"error": "Login erforderlich"})
            return
        with _discover_lock:
            job_id = _discover_state["current_id"]
            cancel_event = _discover_state.get("cancel_event")
            if job_id is None or cancel_event is None:
                self._send_json(409, {"error": "Kein laufender Discover-Run"})
                return
            cancel_event.set()
            job = _discover_state["jobs"].get(job_id)
            if job is not None:
                job["status"] = "cancelling"
        self._send_json(200, {"ok": True, "job_id": job_id})

    def _handle_discover_status(self) -> None:
        """Query ?job_id=X -> Status. Ohne job_id: aktueller current_id zurueck."""
        if not self._session_user():
            self._send_json(401, {"error": "Login erforderlich"})
            return
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        job_id = (query.get("job_id") or [""])[0]
        with _discover_lock:
            if not job_id:
                # ohne job_id: aktuellen laufenden Job zurueckgeben (falls vorhanden)
                job_id = _discover_state["current_id"] or ""
                if not job_id:
                    self._send_json(200, {"status": "idle"})
                    return
            state = _discover_state["jobs"].get(job_id)
        if state is None:
            self._send_json(404, {"error": f"job {job_id!r} unbekannt"})
            return
        self._send_json(200, {**state, "job_id": job_id})

    def _handle_onboarding_scan_folder(self) -> None:
        """Pruefen-Button im Onboarding-Step-3: gibt Files im Ordner aus.

        Body: {path: str} -> {ok, path, files: [{name, size_kb}]}.
        """
        if not self._session_user():
            self._send_json(401, {"error": "Login erforderlich"})
            return
        body = self._read_json()
        path_str = (body.get("path") or "").strip()
        if not path_str:
            self._send_json(400, {"error": "Pfad erforderlich"})
            return
        p = Path(path_str)
        if not p.is_dir():
            self._send_json(404, {"error": f"Verzeichnis nicht gefunden: {path_str}"})
            return
        files = []
        for f in sorted(p.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                files.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024)})
        self._send_json(200, {"ok": True, "path": str(p), "files": files})

    def _handle_onboarding_save(self) -> None:
        """Final-Commit fuer Steps 2-4 des Onboardings.

        Body:
          {
            searches: {keywords: [...], boards: [...]},
            defaults: {locations: [...], date_posted_max_days: int, exclude_keywords: [...]},
            anlagen_folder: str|null,
            anschreiben_examples: [filename, ...],
            extraction_job_id: str|null
          }
        """
        if not self._session_user():
            self._send_json(401, {"error": "Login erforderlich"})
            return
        body = self._read_json()

        # --- 1. searches.yaml ---
        s = body.get("searches") or {}
        d = body.get("defaults") or {}
        keywords = [str(k).strip() for k in s.get("keywords", []) if str(k).strip()]
        locations = [str(l).strip() for l in d.get("locations", []) if str(l).strip()]
        if not keywords:
            self._send_json(400, {"error": "Mindestens ein Suchbegriff erforderlich (Step 2)"})
            return
        if not locations:
            self._send_json(400, {"error": "Mindestens eine Location erforderlich (Step 2)"})
            return
        boards = s.get("boards") or ["arbeitsagentur"]
        exclude_global = [str(x).strip() for x in d.get("exclude_keywords", []) if str(x).strip()]
        try:
            max_days = int(d.get("date_posted_max_days", 14))
        except (TypeError, ValueError):
            max_days = 14

        cfg_dict = {
            "defaults": {
                "locations": locations,
                "date_posted_max_days": max_days,
                "exclude_keywords": exclude_global,
            },
            "searches": [
                {
                    "name": "Standard",
                    "keywords": keywords,
                    "boards": boards,
                    "exclude_keywords": [],
                },
            ],
        }
        try:
            cfg = SearchesConfig.model_validate(cfg_dict)
        except ValidationError as ve:
            self._send_json(400, {"error": _format_validation_error(ve)})
            return
        _save_searches_atomic(self.paths.searches_yaml, cfg)

        # --- 2. anlagen.yaml (optional - nur wenn Folder angegeben + existiert) ---
        anlagen_folder = (body.get("anlagen_folder") or "").strip()
        anlagen_count = 0
        if anlagen_folder:
            folder = Path(anlagen_folder)
            if folder.is_dir():
                from bewerber.shared.anlagen import Anlage
                entries = [
                    Anlage(label=f.stem, files=[f])
                    for f in sorted(folder.iterdir())
                    if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".jpg", ".jpeg", ".png"}
                ]
                if entries:
                    anlagen_cfg = AnlagenConfig(anlagen=entries)
                    _save_anlagen_atomic(self.paths.anlagen_yaml, anlagen_cfg)
                    anlagen_count = len(entries)

        # --- 3. Anschreiben-Stil-Beispiele aus Step-1-Uploads ---
        examples_saved = 0
        extraction_job_id = body.get("extraction_job_id") or ""
        example_names = body.get("anschreiben_examples") or []
        if extraction_job_id and example_names:
            with _onboarding_lock:
                job_state = _onboarding_jobs.get(extraction_job_id) or {}
            upload_dir_str = job_state.get("upload_dir")
            if upload_dir_str:
                upload_dir = Path(upload_dir_str)
                if upload_dir.is_dir():
                    selected_paths = [
                        upload_dir / name
                        for name in example_names
                        if (upload_dir / name).is_file()
                    ]
                    if selected_paths:
                        from bewerber.profile.extractor import save_anschreiben_examples
                        saved = save_anschreiben_examples(
                            selected_paths, self.paths.anschreiben_examples,
                        )
                        examples_saved = len(saved)

        self._send_json(200, {
            "ok": True,
            "redirect": "/",
            "summary": {
                "searches_keywords": len(keywords),
                "locations": len(locations),
                "exclude_keywords": len(exclude_global),
                "anlagen": anlagen_count,
                "anschreiben_examples": examples_saved,
            },
        })

    def _handle_onboarding_status(self) -> None:
        """GET /api/onboarding/status?job_id=X -> aktueller Stand des Hintergrund-Jobs."""
        if not self._session_user():
            self._send_json(401, {"error": "Login erforderlich"})
            return
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        job_id = (query.get("job_id") or [""])[0]
        if not job_id:
            self._send_json(400, {"error": "job_id Query-Parameter fehlt"})
            return
        with _onboarding_lock:
            state = _onboarding_jobs.get(job_id)
        if state is None:
            self._send_json(404, {"error": f"job {job_id!r} unbekannt"})
            return
        self._send_json(200, state)

    def _handle_login(self) -> None:
        body = self._read_json()
        username = (body.get("username") or "").strip()
        passwort = body.get("passwort") or ""
        if not username or not passwort:
            self._send_json(400, {"error": "Username und Passwort sind erforderlich."})
            return
        if not auth.authenticate(_registry_path(), username, passwort):
            self._send_json(401, {"error": "Login fehlgeschlagen."})
            return
        payload = json.dumps({"ok": True, "redirect": "/"}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self._set_session_cookie_header(username)
        self.end_headers()
        self.wfile.write(payload)

    def _handle_register(self) -> None:
        body = self._read_json()
        vorname = (body.get("vorname") or "").strip()
        nachname = (body.get("nachname") or "").strip()
        passwort = body.get("passwort") or ""
        invite = (body.get("invite_code") or "").strip()
        if not vorname or not nachname or not passwort:
            self._send_json(400, {"error": "Vorname, Nachname und Passwort sind erforderlich."})
            return
        if len(passwort) < 8:
            self._send_json(400, {"error": "Passwort muss mindestens 8 Zeichen haben."})
            return
        if not _invite_code() or invite != _invite_code():
            self._send_json(403, {"error": "Ungueltiger Einladungs-Code."})
            return
        username = auth.register_user(_registry_path(), vorname, nachname, passwort)
        # Per-User-Workspace anlegen + Starter-Configs aus den .example-Vorlagen kopieren
        user_paths = Paths(user=username)
        user_paths.data_dir.mkdir(parents=True, exist_ok=True)
        (user_paths.bewerbungen).mkdir(parents=True, exist_ok=True)
        bewerber_dir = Paths().bewerber_dir
        for example_name, target in (
            ("searches.yaml.example", user_paths.searches_yaml),
            ("anlagen.yaml.example", user_paths.anlagen_yaml),
        ):
            example = bewerber_dir / example_name
            if example.is_file() and not target.is_file():
                target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        payload = json.dumps(
            {"ok": True, "username": username, "redirect": "/"}, ensure_ascii=False
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self._set_session_cookie_header(username)
        self.end_headers()
        self.wfile.write(payload)

    def _handle_account_delete(self) -> None:
        """Loescht den eigenen Account RESTLOS: kompletter User-Workspace
        (Dokumente, Bewerbungen, Suchen, Profil, Themes, State) + Registry-
        Eintrag. Erfordert explizite Bestaetigung im Body ({"confirm": true})."""
        username = self._require_session()
        if not username:
            return
        body = self._read_json()
        if body.get("confirm") is not True:
            self._send_json(400, {
                "error": "Bestaetigung fehlt: confirm=true erforderlich",
            })
            return

        user_dir = Paths(user=username).data_dir
        users_root = Paths().users_dir
        # Sicherheitsgurt: nur echte User-Unterordner loeschen
        if user_dir.resolve().parent != users_root.resolve():
            self._send_json(500, {"error": "Unerwarteter Workspace-Pfad - Abbruch"})
            return
        if user_dir.is_dir():
            shutil.rmtree(user_dir)
        auth.delete_user(_registry_path(), username)
        log.info("[account] %s hat den eigenen Account geloescht", username)

        payload = json.dumps({"ok": True, "redirect": "/login"}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self._clear_session_cookie_header()
        self.end_headers()
        self.wfile.write(payload)

    def _handle_logout(self) -> None:
        payload = json.dumps({"ok": True, "redirect": "/login"}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self._clear_session_cookie_header()
        self.end_headers()
        self.wfile.write(payload)

    def _handle_batch_tailor(self) -> None:
        """Streaming-Endpoint: tailored mehrere Jobs in einem Rutsch.

        Body: {job_ids: [str, ...], starttermin: str, gehalt?: str}
        Kontakt_name wird absichtlich NICHT als Batch-Param unterstuetzt -
        ist pro Stelle individuell.
        """
        body = self._read_json()
        job_ids = body.get("job_ids", [])
        starttermin = (body.get("starttermin") or "").strip()
        gehalt = (body.get("gehalt") or "").strip() or None
        sprache = body.get("sprache") or "de"
        if not isinstance(job_ids, list) or not job_ids:
            self._send_json(400, {"error": "job_ids (Liste) erforderlich"})
            return
        if not starttermin:
            self._send_json(400, {"error": "starttermin ist erforderlich"})
            return

        # Streaming-Header
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def emit(event: dict) -> None:
            self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        from datetime import date
        from bewerber.shared.llm import LLMClient
        from bewerber.tailoring.orchestrator import TailorInput, tailor

        llm = LLMClient.for_generation()
        paths = self.paths  # bind in request context before the loop
        choice = _build_template_choice(body, paths)
        total = len(job_ids)
        emit({"event": "begin", "total": total})

        for i, jid in enumerate(job_ids):
            emit({"event": "start", "index": i, "job_id": jid})
            try:
                state = load_state(self.paths.state_json)
                job = state.jobs.get(jid)
                if job is None:
                    emit({"event": "error", "index": i, "job_id": jid, "error": "Job nicht in state.json"})
                    continue
                if job.tailored_dir:
                    emit({
                        "event": "skipped_already_tailored", "index": i,
                        "job_id": jid, "tailored_dir": job.tailored_dir,
                        "label": f"{job.raw.title} - {job.raw.company}",
                    })
                    continue

                emit({
                    "event": "label", "index": i,
                    "label": f"{job.raw.title} - {job.raw.company}",
                })

                result = tailor(TailorInput(
                    posting_text=job.raw.description or "",
                    firma=job.raw.company,
                    rolle=job.raw.title,
                    datum=date.today().isoformat(),
                    kontakt_name=None,  # bewusst leer fuer Batch
                    source_url=job.raw.url or None,
                    snapshot_dir=None,
                    llm=llm,
                    paths=paths,
                    starttermin=starttermin,
                    gehalt=gehalt,
                    sprache=sprache,
                    template=choice,
                ))
                emit({
                    "event": "done", "index": i,
                    "job_id": jid, "output_dir": str(result.output_dir),
                })
            except Exception as e:  # noqa: BLE001 - eine fehlerhafte URL stoppt nicht den Batch
                emit({
                    "event": "error", "index": i,
                    "job_id": jid, "error": str(e)[:300],
                })

        emit({"event": "complete", "total": total})

    def _handle_failed_clear(self) -> None:
        state = load_state(self.paths.state_json)
        n = len(state.failed_urls)
        state.failed_urls = []
        save_state(self.paths.state_json, state)
        self._send_json(200, {"ok": True, "removed": n})

    def _handle_failed_remove(self) -> None:
        body = self._read_json()
        url = (body.get("url") or "").strip()
        if not url:
            self._send_json(400, {"error": "url required"})
            return
        state = load_state(self.paths.state_json)
        before = len(state.failed_urls)
        state.failed_urls = [f for f in state.failed_urls if f.url != url]
        save_state(self.paths.state_json, state)
        self._send_json(200, {"ok": True, "removed": before - len(state.failed_urls)})

    def _handle_set_default_template(self) -> None:
        body = self._read_json()
        set_id = (body.get("set_id") or "").strip()
        if not UserTemplateStore(self.paths).has_set(set_id):
            self._send_json(400, {"error": f"unbekanntes Set {set_id!r}"})
            return
        s = load_settings(self.paths)
        s.default_template_set = set_id
        save_settings(self.paths, s)
        self._send_json(200, {"ok": True, "default": set_id})

    def _handle_notes_set(self) -> None:
        body = self._read_json()
        job_id = body.get("job_id")
        if not job_id:
            self._send_json(400, {"error": "job_id required"})
            return
        # Notes ist optional - leerer String erlaubt (= Loeschen)
        notes = body.get("notes", "")
        if not isinstance(notes, str):
            self._send_json(400, {"error": "notes must be a string"})
            return

        state = load_state(self.paths.state_json)
        job = state.jobs.get(job_id)
        if job is None:
            self._send_json(404, {"error": f"job {job_id!r} not found"})
            return

        job.notes = notes
        save_state(self.paths.state_json, state)
        self._send_json(200, {"ok": True, "job_id": job_id, "length": len(notes)})

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

    def _resolve_job_dir(self, job_id: str):
        """Gibt (tailored_dir: Path) des Jobs aus der state.json des eingeloggten
        Users zurueck, oder sendet 401/404 und gibt None."""
        if self._require_session() is None:
            return None
        if not job_id:
            self._send_json(400, {"error": "job_id erforderlich"})
            return None
        state = load_state(self.paths.state_json)
        job = state.jobs.get(job_id)
        if job is None or not job.tailored_dir:
            self._send_json(404, {"error": "Job/Ordner nicht gefunden"})
            return None
        td = Path(job.tailored_dir)
        if not td.is_dir():
            self._send_json(404, {"error": "Ordner existiert nicht"})
            return None
        return td

    def _handle_job_files(self, query: dict) -> None:
        job_id = (query.get("job_id") or [""])[0]
        td = self._resolve_job_dir(job_id)
        if td is None:
            return
        files = []
        for p in sorted(td.rglob("*")):
            if p.is_file() and not p.is_symlink():
                rel = str(p.relative_to(td))
                if not _is_deliverable(rel):
                    continue
                files.append({"name": rel, "size": p.stat().st_size})
        self._send_json(200, {"files": files})

    def _handle_download(self, query: dict) -> None:
        # Einzeldatei-Download bewusst OHNE _is_deliverable-Filter (siehe dort):
        # pfad-validiert + nutzergebunden, erlaubt gezielten Zugriff auf alle Dateien.
        job_id = (query.get("job_id") or [""])[0]
        rel = (query.get("file") or [""])[0]
        td = self._resolve_job_dir(job_id)
        if td is None:
            return
        if not rel:
            self._send_json(400, {"error": "file erforderlich"})
            return
        target = (td / rel).resolve()
        if not str(target).startswith(str(td.resolve()) + os.sep) or not target.is_file():
            self._send_json(400, {"error": "ungueltiger Pfad"})
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle_download_zip(self, query: dict) -> None:
        job_id = (query.get("job_id") or [""])[0]
        td = self._resolve_job_dir(job_id)
        if td is None:
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(td.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    rel = str(p.relative_to(td))
                    if not _is_deliverable(rel):
                        continue
                    zf.write(p, arcname=rel)
        data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{td.name}.zip"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def _load_searches_config(paths: Paths) -> SearchesConfig:
    """Load searches.yaml; return empty SearchesConfig when missing."""
    p = paths.searches_yaml
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
    """Erzeugt eine Handler-Klasse. paths wird ignoriert — der Handler leitet
    Paths pro Request aus der Session ab (self.paths-Property)."""
    return type("_BoundHandler", (_Handler,), {})


def serve(paths: Optional[Paths] = None, port: int = 0) -> HTTPServer:
    """Create and return a configured HTTPServer.

    `port=0` requests an ephemeral port. The caller is responsible for calling
    `serve_forever()` and `shutdown()`. Returned server has `server_address`
    available with the actual port.
    """
    paths = paths or Paths()
    handler = make_handler(paths)
    return HTTPServer(("127.0.0.1", port), handler)
