"""Tests for the dashboard HTTP server endpoints."""
import json
import threading
import urllib.request
import urllib.error
from pathlib import Path

import pytest

from bewerber.shared.paths import Paths
from bewerber.shared.state import save_state, load_state
from bewerber.shared.state_schema import (
    BewerberState, JobStatus, RawJob, TrackedJob,
)
from bewerber.dashboard.server import serve as start_server


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    """Start an ephemeral HTTP server bound to a fresh state.json under tmp_path."""
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    (tmp_path / "bewerber").mkdir()
    # Seed one job
    state = BewerberState(jobs={
        "arbeitsagentur-x1": TrackedJob(raw=RawJob(
            board="arbeitsagentur", external_id="x1",
            url="https://x", title="KI Manager", company="Acme", location="Leipzig",
        )),
    })
    save_state(Paths().state_json, state)

    httpd = start_server(paths=Paths(), port=0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def _post_json(port: int, path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(port: int, path: str) -> tuple[int, str]:
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)
        return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_get_index_returns_dashboard_html(running_server):
    code, body = _get(running_server, "/")
    assert code == 200
    assert "<title>Bewerber-Dashboard</title>" in body
    assert "arbeitsagentur-x1" in body


def test_mark_applied_updates_status_and_history(running_server, tmp_path):
    code, body = _post_json(running_server, "/api/mark", {
        "job_id": "arbeitsagentur-x1",
        "status": "applied",
        "application_link": "https://applied.example",
    })
    assert code == 200, body
    assert body["ok"] is True

    state = load_state(Paths().state_json)
    job = state.jobs["arbeitsagentur-x1"]
    assert job.status == JobStatus.APPLIED
    assert job.application_link == "https://applied.example"
    assert len(job.status_history) == 1
    assert job.status_history[0].status == JobStatus.APPLIED


def test_mark_invalid_status_returns_400(running_server):
    code, body = _post_json(running_server, "/api/mark", {
        "job_id": "arbeitsagentur-x1",
        "status": "bogus-state",
    })
    assert code == 400
    assert "invalid status" in body["error"].lower() or "bogus" in body["error"].lower()


def test_mark_unknown_job_returns_404(running_server):
    code, body = _post_json(running_server, "/api/mark", {
        "job_id": "nonexistent-9999",
        "status": "applied",
    })
    assert code == 404
    assert "not found" in body["error"].lower()


def test_note_appends_timestamped_entry(running_server):
    code, _ = _post_json(running_server, "/api/note", {
        "job_id": "arbeitsagentur-x1",
        "text": "Recruiter angerufen am 15.06.",
    })
    assert code == 200
    state = load_state(Paths().state_json)
    notes = state.jobs["arbeitsagentur-x1"].notes
    assert "Recruiter angerufen" in notes
    # Timestamp prefix
    assert "[" in notes and "]" in notes


def test_open_folder_path_not_exists_returns_404(running_server):
    code, body = _post_json(running_server, "/api/open-folder", {
        "path": "/definitely/does/not/exist/xyz123",
    })
    assert code == 404
    assert "exist" in body["error"].lower()


def test_unknown_endpoint_returns_404(running_server):
    code, body = _post_json(running_server, "/api/bogus", {})
    assert code == 404
