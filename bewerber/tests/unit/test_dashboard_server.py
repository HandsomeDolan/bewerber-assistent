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


# ---------------------------------------------------------------------------
# Searches editor endpoints
# ---------------------------------------------------------------------------

def test_get_searches_returns_empty_when_yaml_missing(running_server, tmp_path):
    """No searches.yaml on disk -> defaults to empty SearchesConfig."""
    code, body = _get(running_server, "/api/searches")
    assert code == 200
    cfg = json.loads(body)
    assert cfg["searches"] == []
    assert cfg["defaults"]["locations"] == []
    assert cfg["defaults"]["exclude_keywords"] == []


def test_get_searches_returns_existing_yaml(running_server, tmp_path):
    """API echoes whatever's currently in searches.yaml."""
    import yaml
    (tmp_path / "bewerber" / "searches.yaml").write_text(yaml.safe_dump({
        "defaults": {"locations": ["Leipzig"], "exclude_keywords": ["SPS"]},
        "searches": [{
            "name": "KI",
            "keywords": ["KI Manager"],
            "boards": ["arbeitsagentur"],
            "exclude_keywords": ["Vertrieb"],
        }],
    }))
    code, body = _get(running_server, "/api/searches")
    assert code == 200
    cfg = json.loads(body)
    assert cfg["defaults"]["exclude_keywords"] == ["SPS"]
    assert cfg["searches"][0]["name"] == "KI"
    assert cfg["searches"][0]["exclude_keywords"] == ["Vertrieb"]


def test_post_searches_persists_atomically(running_server, tmp_path):
    """Valid POST writes a well-formed searches.yaml."""
    new_cfg = {
        "defaults": {
            "locations": ["Leipzig", "Remote"],
            "date_posted_max_days": 21,
            "min_fit_score": 6,
            "exclude_keywords": ["SPS", "PLS"],
        },
        "searches": [{
            "name": "AI Consulting",
            "keywords": ["AI Consultant", "KI Berater"],
            "boards": ["arbeitsagentur", "linkedin"],
            "exclude_keywords": [],
        }],
    }
    code, body = _post_json(running_server, "/api/searches", new_cfg)
    assert code == 200, body
    assert body["ok"] is True
    assert body["searches"] == 1

    # File on disk reflects what was sent
    import yaml
    written = yaml.safe_load((tmp_path / "bewerber" / "searches.yaml").read_text())
    assert written["defaults"]["exclude_keywords"] == ["SPS", "PLS"]
    assert written["searches"][0]["name"] == "AI Consulting"
    assert written["searches"][0]["boards"] == ["arbeitsagentur", "linkedin"]

    # No leftover .tmp from the atomic write
    assert not (tmp_path / "bewerber" / "searches.yaml.tmp").exists()


def test_post_searches_validation_error_returns_400(running_server, tmp_path):
    """Invalid board literal -> 400 with structured error message."""
    bad = {
        "searches": [{
            "name": "X",
            "keywords": ["x"],
            "boards": ["facebook"],  # not in VALID_BOARDS
        }],
    }
    code, body = _post_json(running_server, "/api/searches", bad)
    assert code == 400
    # Error should mention the invalid field path
    assert "boards" in body["error"]
    # File should NOT have been overwritten
    assert not (tmp_path / "bewerber" / "searches.yaml").exists()


def test_post_searches_extra_field_rejected(running_server, tmp_path):
    """Pydantic extra='forbid' surfaces unknown fields as 400."""
    bad = {
        "defaults": {"bogus_field": 123},
        "searches": [],
    }
    code, body = _post_json(running_server, "/api/searches", bad)
    assert code == 400


def test_get_searches_html_page_renders(running_server):
    """/searches returns the editor HTML."""
    code, body = _get(running_server, "/searches")
    assert code == 200
    assert "Suchkonfiguration" in body
    assert "initial-config" in body  # embedded JSON script tag


# ---------------------------------------------------------------------------
# Anlagen editor endpoints
# ---------------------------------------------------------------------------

def test_get_anlagen_returns_empty_when_yaml_missing(running_server, tmp_path):
    code, body = _get(running_server, "/api/anlagen")
    assert code == 200
    cfg = json.loads(body)
    assert cfg["anlagen"] == []


def test_get_anlagen_returns_existing_yaml(running_server, tmp_path):
    import yaml
    (tmp_path / "bewerber" / "anlagen.yaml").write_text(yaml.safe_dump({
        "anlagen": [
            {"label": "Arbeitszeugnisse", "files": ["/some/cert.pdf"]},
            {"label": "Technikerzeugnis", "files": ["/p1.pdf", "/p2.pdf"]},
        ],
    }, allow_unicode=True))
    code, body = _get(running_server, "/api/anlagen")
    assert code == 200
    cfg = json.loads(body)
    assert len(cfg["anlagen"]) == 2
    assert cfg["anlagen"][0]["label"] == "Arbeitszeugnisse"
    assert cfg["anlagen"][1]["files"] == ["/p1.pdf", "/p2.pdf"]


def test_post_anlagen_persists_atomically(running_server, tmp_path):
    """Valid POST writes anlagen.yaml; missing-files list reported in response."""
    new_cfg = {
        "anlagen": [
            {"label": "Zeugnis", "files": ["/does/not/exist.pdf"]},
        ],
    }
    code, body = _post_json(running_server, "/api/anlagen", new_cfg)
    assert code == 200, body
    assert body["ok"] is True
    assert body["anlagen"] == 1
    assert "/does/not/exist.pdf" in body["missing"]

    import yaml
    written = yaml.safe_load((tmp_path / "bewerber" / "anlagen.yaml").read_text())
    assert written["anlagen"][0]["label"] == "Zeugnis"
    assert not (tmp_path / "bewerber" / "anlagen.yaml.tmp").exists()


def test_post_anlagen_validation_error_returns_400(running_server, tmp_path):
    """Missing required 'label' field -> 400, file unchanged."""
    bad = {"anlagen": [{"files": ["/foo.pdf"]}]}   # no label
    code, body = _post_json(running_server, "/api/anlagen", bad)
    assert code == 400
    assert "label" in body["error"]
    assert not (tmp_path / "bewerber" / "anlagen.yaml").exists()


def test_verify_anlagen_returns_missing_paths(running_server, tmp_path):
    """Verify endpoint distinguishes existing vs missing files."""
    real = tmp_path / "real.pdf"
    real.write_bytes(b"%PDF-1.4")
    code, body = _post_json(running_server, "/api/anlagen/verify", {
        "paths": [str(real), "/definitely/missing.pdf"],
    })
    assert code == 200
    assert body["missing"] == ["/definitely/missing.pdf"]


def test_verify_anlagen_rejects_non_list(running_server):
    code, body = _post_json(running_server, "/api/anlagen/verify", {"paths": "/wrong.pdf"})
    assert code == 400


def test_get_anlagen_html_page_renders(running_server):
    code, body = _get(running_server, "/anlagen")
    assert code == 200
    assert "Anlagen verwalten" in body
    assert "initial-config" in body


# ---------------------------------------------------------------------------
# Manual add-posting endpoint
# ---------------------------------------------------------------------------

def test_add_posting_missing_fields_returns_400(running_server):
    code, body = _post_json(running_server, "/api/add-posting", {"url": "https://x"})
    assert code == 400
    assert "erforderlich" in body["error"]


def test_add_posting_without_master_profile_returns_500(running_server, tmp_path):
    """Fixture seeds a job at https://x already; use a fresh URL here."""
    code, body = _post_json(running_server, "/api/add-posting", {
        "url": "https://fresh.example/job", "firma": "F", "rolle": "R",
    })
    assert code == 500
    assert "master_profile" in body["error"]


def test_add_posting_duplicate_url_returns_409(running_server, tmp_path):
    """Existing job with the same URL -> 409, no scrape happens."""
    # Seed an existing job
    state = BewerberState(jobs={
        "arbeitsagentur-x1": TrackedJob(raw=RawJob(
            board="arbeitsagentur", external_id="x1",
            url="https://dup.example/job", title="t", company="c", location="",
        )),
    })
    save_state(Paths().state_json, state)

    code, body = _post_json(running_server, "/api/add-posting", {
        "url": "https://dup.example/job", "firma": "X", "rolle": "Y",
    })
    assert code == 409
    assert "bereits erfasst" in body["error"]


def test_add_posting_happy_path(running_server, tmp_path, mocker):
    """Snapshot + Scoring mocked -> state has the new manual job."""
    # Master profile required
    (tmp_path / "bewerber" / "master_profile.yaml").write_text(
        "person: {name: x, email: x@y.de}\nberufsprofil: x\nzielposition: []",
    )

    # Mock heavy dependencies
    mocker.patch(
        "bewerber.tailoring.snapshot.snapshot_url",
        return_value="Job description text from URL.",
    )
    from bewerber.shared.state_schema import Scoring as _Scoring
    mocker.patch(
        "bewerber.discovery.scoring.score_job",
        return_value=_Scoring(
            fit_score=8, begruendung="passt", matched_skills=["Python"],
            missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
        ),
    )
    mocker.patch("bewerber.shared.llm.LLMClient.for_scoring", return_value=mocker.Mock())

    code, body = _post_json(running_server, "/api/add-posting", {
        "url": "https://stepstone.de/job/12345",
        "firma": "BMW Group",
        "rolle": "AI Product Manager",
    })
    assert code == 200, body
    assert body["ok"] is True
    assert body["fit_score"] == 8
    assert body["job_id"].startswith("manual-")

    # State has the new job
    state = load_state(Paths().state_json)
    assert body["job_id"] in state.jobs
    job = state.jobs[body["job_id"]]
    assert job.raw.company == "BMW Group"
    assert job.raw.title == "AI Product Manager"
    assert job.scoring.fit_score == 8


# ---------------------------------------------------------------------------
# Server-side tailor endpoint
# ---------------------------------------------------------------------------

def test_tailor_missing_fields_returns_400(running_server):
    code, body = _post_json(running_server, "/api/tailor", {"job_id": "x"})
    assert code == 400


def test_tailor_unknown_job_returns_404(running_server):
    code, body = _post_json(running_server, "/api/tailor", {
        "job_id": "nope-9999", "starttermin": "ab sofort",
    })
    assert code == 404


def test_tailor_happy_path(running_server, tmp_path, mocker):
    """Tailor orchestrator mocked -> endpoint forwards form data correctly."""
    # Seed a scored job
    from bewerber.shared.state_schema import Scoring as _Scoring
    state = BewerberState(jobs={
        "arbeitsagentur-y1": TrackedJob(
            raw=RawJob(
                board="arbeitsagentur", external_id="y1",
                url="https://x.example", title="KI Manager", company="Acme",
                location="Leipzig", description="job desc",
            ),
            scoring=_Scoring(
                fit_score=7, begruendung="ok", matched_skills=[], missing_skills=[],
                red_flags=[], verbessern_in_anschreiben=[],
            ),
        ),
    })
    save_state(Paths().state_json, state)

    fake_tailor = mocker.patch("bewerber.tailoring.orchestrator.tailor")
    fake_tailor.return_value = mocker.Mock(output_dir=Path("/tmp/bewerbung-out"))
    mocker.patch("bewerber.shared.llm.LLMClient.for_generation", return_value=mocker.Mock())

    code, body = _post_json(running_server, "/api/tailor", {
        "job_id": "arbeitsagentur-y1",
        "starttermin": "01.08.2026",
        "gehalt": "65000",
        "kontakt_name": "Frau Müller",
    })
    assert code == 200, body
    assert body["ok"] is True
    assert body["output_dir"] == "/tmp/bewerbung-out"

    # Verify TailorInput was constructed correctly
    args, kwargs = fake_tailor.call_args
    inp = args[0] if args else kwargs.get("inp")
    assert inp.firma == "Acme"
    assert inp.rolle == "KI Manager"
    assert inp.starttermin == "01.08.2026"
    assert inp.gehalt == "65000"
    assert inp.kontakt_name == "Frau Müller"
    assert inp.posting_text == "job desc"


# ---------------------------------------------------------------------------
# /api/notes-set (full-replace, no timestamp)
# ---------------------------------------------------------------------------

def test_notes_set_replaces_entire_notes_field(running_server):
    code, body = _post_json(running_server, "/api/notes-set", {
        "job_id": "arbeitsagentur-x1",
        "notes": "Frei-Text\nMehrere Zeilen.",
    })
    assert code == 200, body
    assert body["ok"] is True

    state = load_state(Paths().state_json)
    assert state.jobs["arbeitsagentur-x1"].notes == "Frei-Text\nMehrere Zeilen."


def test_notes_set_overwrites_prior_notes(running_server):
    # First set
    _post_json(running_server, "/api/notes-set", {"job_id": "arbeitsagentur-x1", "notes": "alt"})
    # Then replace
    code, _ = _post_json(running_server, "/api/notes-set", {"job_id": "arbeitsagentur-x1", "notes": "neu"})
    assert code == 200
    assert load_state(Paths().state_json).jobs["arbeitsagentur-x1"].notes == "neu"


def test_notes_set_allows_empty_string_to_clear_notes(running_server):
    """Notes loeschen indem man leeren String sendet."""
    _post_json(running_server, "/api/notes-set", {"job_id": "arbeitsagentur-x1", "notes": "was"})
    code, _ = _post_json(running_server, "/api/notes-set", {"job_id": "arbeitsagentur-x1", "notes": ""})
    assert code == 200
    assert load_state(Paths().state_json).jobs["arbeitsagentur-x1"].notes == ""


def test_notes_set_missing_job_id_returns_400(running_server):
    code, body = _post_json(running_server, "/api/notes-set", {"notes": "x"})
    assert code == 400


def test_notes_set_unknown_job_returns_404(running_server):
    code, body = _post_json(running_server, "/api/notes-set", {
        "job_id": "ghost-9999", "notes": "x",
    })
    assert code == 404


def test_notes_set_non_string_notes_returns_400(running_server):
    code, body = _post_json(running_server, "/api/notes-set", {
        "job_id": "arbeitsagentur-x1", "notes": ["nicht", "string"],
    })
    assert code == 400


def test_tailor_orchestrator_failure_returns_502(running_server, tmp_path, mocker):
    """If tailor() raises, the endpoint returns 502 with the message."""
    from bewerber.shared.state_schema import Scoring as _Scoring
    state = BewerberState(jobs={
        "arbeitsagentur-z1": TrackedJob(
            raw=RawJob(
                board="arbeitsagentur", external_id="z1",
                url="", title="t", company="c", location="",
                description="d",
            ),
            scoring=_Scoring(
                fit_score=5, begruendung="x", matched_skills=[], missing_skills=[],
                red_flags=[], verbessern_in_anschreiben=[],
            ),
        ),
    })
    save_state(Paths().state_json, state)

    mocker.patch(
        "bewerber.tailoring.orchestrator.tailor",
        side_effect=RuntimeError("LLM quota out"),
    )
    mocker.patch("bewerber.shared.llm.LLMClient.for_generation", return_value=mocker.Mock())

    code, body = _post_json(running_server, "/api/tailor", {
        "job_id": "arbeitsagentur-z1", "starttermin": "ab sofort",
    })
    assert code == 502
    assert "LLM quota out" in body["error"]
