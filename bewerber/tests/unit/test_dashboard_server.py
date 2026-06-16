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
    BewerberState, FailedUrl, JobStatus, RawJob, TrackedJob,
)
from bewerber.dashboard.server import serve as start_server


SESSION_COOKIE = "bewerber_session=Test%20User"


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    """Start an ephemeral HTTP server bound to a fresh state.json under tmp_path."""
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    (tmp_path / "bewerber").mkdir()
    # Stub master_profile.yaml so dashboard-routing doesn't redirect to /onboarding
    (tmp_path / "bewerber" / "master_profile.yaml").write_text(
        "person: {name: x, email: x@y.de}\nberufsprofil: x\nzielposition: []",
    )
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


def _post_json(port: int, path: str, body: dict, *, with_session: bool = True) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if with_session:
        headers["Cookie"] = SESSION_COOKIE
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(port: int, path: str, *, with_session: bool = True, follow_redirects: bool = False) -> tuple[int, str]:
    """GET with optional session cookie + control of redirect-following.

    follow_redirects=False is the default so tests can assert 302 + Location header.
    """
    headers = {}
    if with_session:
        headers["Cookie"] = SESSION_COOKIE

    if follow_redirects:
        try:
            resp = urllib.request.urlopen(
                urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers),
                timeout=5,
            )
            return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    # Manuelles Handling: urllib folgt sonst 302 automatisch
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    # Location-Header bei 302 in den body packen, damit Tests einfach pruefen koennen
    if resp.status in (301, 302, 303, 307, 308):
        body = f"REDIRECT to: {resp.getheader('Location')}\n" + body
    conn.close()
    return resp.status, body


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
    """Fixture seeds a job at https://x already; use a fresh URL here.
    Fixture seeded master_profile.yaml fuer das Routing - hier loeschen,
    damit der Endpoint die fehlende Master-Profile-Pruefung trifft."""
    (tmp_path / "bewerber" / "master_profile.yaml").unlink()
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
# Batch add-postings + failed_urls Management
# ---------------------------------------------------------------------------

def test_batch_add_postings_streams_ndjson_events(running_server, tmp_path, mocker):
    """Happy path: 2 URLs, snapshot + extract_and_score gemockt."""
    # Master-Profil anlegen
    (tmp_path / "bewerber" / "master_profile.yaml").write_text(
        "person: {name: x, email: x@y.de}\nberufsprofil: x\nzielposition: []",
    )
    # Snapshots mocken
    mocker.patch(
        "bewerber.tailoring.snapshot.snapshot_url",
        side_effect=lambda url, out: f"Job text fuer {url}",
    )
    # LLM-Call mocken
    from bewerber.discovery.scoring import BatchScoreResult
    from bewerber.shared.state_schema import Scoring as _Sc

    def fake_extract(posting_text, master_yaml_text, llm):
        # Liefere passenden Firma/Rolle abhaengig vom Text
        if "abc" in posting_text:
            return BatchScoreResult(
                firma="Acme GmbH", rolle="AI Manager",
                scoring=_Sc(fit_score=8, begruendung="ok", matched_skills=[],
                            missing_skills=[], red_flags=[], verbessern_in_anschreiben=[]),
            )
        return BatchScoreResult(
            firma="Beta AG", rolle="Senior Consultant",
            scoring=_Sc(fit_score=5, begruendung="ok", matched_skills=[],
                        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[]),
        )
    mocker.patch("bewerber.dashboard.server.LLMClient", create=True)
    mocker.patch("bewerber.discovery.scoring.extract_and_score", side_effect=fake_extract)
    mocker.patch("bewerber.shared.llm.LLMClient.for_scoring", return_value=mocker.Mock())

    body = {"urls": ["https://x.example/abc", "https://x.example/xyz"]}
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/batch-add-postings",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/x-ndjson")

    raw = resp.read().decode("utf-8")
    events = [json.loads(ln) for ln in raw.strip().split("\n") if ln.strip()]

    # Begin + complete einrahmen
    assert events[0]["event"] == "begin"
    assert events[0]["total"] == 2
    assert events[-1]["event"] == "complete"

    # Pro URL: start, mind. ein phase, extracted, done
    starts = [e for e in events if e["event"] == "start"]
    extracted = [e for e in events if e["event"] == "extracted"]
    done = [e for e in events if e["event"] == "done"]
    assert len(starts) == 2
    assert len(extracted) == 2
    assert len(done) == 2
    # firma/rolle aus dem fake LLM
    assert {e["firma"] for e in extracted} == {"Acme GmbH", "Beta AG"}

    # State: beide Jobs persistiert
    state = load_state(Paths().state_json)
    manual_jobs = [j for j in state.jobs.values() if j.raw.board == "manual"]
    assert len(manual_jobs) == 2


def test_batch_add_postings_handles_per_url_errors_and_stores_in_failed_urls(
    running_server, tmp_path, mocker,
):
    """Eine URL crasht beim Snapshot -> error-Event + landet in failed_urls."""
    (tmp_path / "bewerber" / "master_profile.yaml").write_text(
        "person: {name: x, email: x@y.de}\nberufsprofil: x\nzielposition: []",
    )

    def snap(url, out):
        if "bad" in url:
            raise RuntimeError("snapshot crashed")
        return "good posting text"

    mocker.patch("bewerber.tailoring.snapshot.snapshot_url", side_effect=snap)
    from bewerber.discovery.scoring import BatchScoreResult
    from bewerber.shared.state_schema import Scoring as _Sc
    mocker.patch(
        "bewerber.discovery.scoring.extract_and_score",
        return_value=BatchScoreResult(
            firma="OK GmbH", rolle="Manager",
            scoring=_Sc(fit_score=7, begruendung="ok", matched_skills=[],
                        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[]),
        ),
    )
    mocker.patch("bewerber.shared.llm.LLMClient.for_scoring", return_value=mocker.Mock())

    body = {"urls": ["https://x.example/bad-url", "https://x.example/good-url"]}
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/batch-add-postings",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read().decode("utf-8")
    events = [json.loads(ln) for ln in raw.strip().split("\n") if ln.strip()]

    error_events = [e for e in events if e["event"] == "error"]
    done_events = [e for e in events if e["event"] == "done"]
    assert len(error_events) == 1
    assert len(done_events) == 1
    assert "bad-url" in error_events[0]["url"]

    # failed_urls persistiert
    state = load_state(Paths().state_json)
    assert len(state.failed_urls) == 1
    assert "bad-url" in state.failed_urls[0].url
    assert "snapshot crashed" in state.failed_urls[0].error


def test_batch_add_postings_rejects_empty_urls_list(running_server):
    code, body = _post_json(running_server, "/api/batch-add-postings", {"urls": []})
    assert code == 400


def test_batch_add_postings_rejects_missing_master_profile(running_server, tmp_path):
    """Fixture seeded master_profile.yaml fuer das Routing - hier loeschen,
    damit der Endpoint die fehlende Master-Profile-Pruefung trifft."""
    (tmp_path / "bewerber" / "master_profile.yaml").unlink()
    code, body = _post_json(running_server, "/api/batch-add-postings", {
        "urls": ["https://x"],
    })
    assert code == 500
    assert "master_profile" in body["error"]


def test_failed_urls_clear_removes_all(running_server, tmp_path):
    state = BewerberState(failed_urls=[
        FailedUrl(url="https://a", error="e1", at="2026-06-15T10:00:00"),
        FailedUrl(url="https://b", error="e2", at="2026-06-15T11:00:00"),
    ])
    save_state(Paths().state_json, state)

    code, body = _post_json(running_server, "/api/failed-urls/clear", {})
    assert code == 200
    assert body["removed"] == 2
    assert load_state(Paths().state_json).failed_urls == []


def test_failed_urls_remove_drops_one(running_server, tmp_path):
    state = BewerberState(failed_urls=[
        FailedUrl(url="https://a", error="e1", at="2026-06-15T10:00:00"),
        FailedUrl(url="https://b", error="e2", at="2026-06-15T11:00:00"),
    ])
    save_state(Paths().state_json, state)

    code, body = _post_json(running_server, "/api/failed-urls/remove", {"url": "https://a"})
    assert code == 200
    after = load_state(Paths().state_json).failed_urls
    assert len(after) == 1
    assert after[0].url == "https://b"


def test_failed_urls_remove_missing_url_400(running_server):
    code, _ = _post_json(running_server, "/api/failed-urls/remove", {})
    assert code == 400


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


# ---------------------------------------------------------------------------
# Batch-Tailor (NDJSON stream)
# ---------------------------------------------------------------------------

def _seed_two_jobs():
    from bewerber.shared.state_schema import Scoring as _Sc
    state = BewerberState(jobs={
        "arbeitsagentur-a": TrackedJob(
            raw=RawJob(
                board="arbeitsagentur", external_id="a",
                url="https://a", title="KI Manager", company="Acme",
                location="Leipzig", description="job desc A",
            ),
            scoring=_Sc(fit_score=7, begruendung="ok", matched_skills=[],
                        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[]),
        ),
        "arbeitsagentur-b": TrackedJob(
            raw=RawJob(
                board="arbeitsagentur", external_id="b",
                url="https://b", title="Senior Consultant", company="Beta",
                location="Berlin", description="job desc B",
            ),
            scoring=_Sc(fit_score=6, begruendung="ok", matched_skills=[],
                        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[]),
        ),
    })
    save_state(Paths().state_json, state)


def test_batch_tailor_streams_ndjson_per_job(running_server, tmp_path, mocker):
    _seed_two_jobs()
    fake_tailor = mocker.patch("bewerber.tailoring.orchestrator.tailor")
    fake_tailor.return_value = mocker.Mock(output_dir=Path("/tmp/out"))
    mocker.patch("bewerber.shared.llm.LLMClient.for_generation", return_value=mocker.Mock())

    body = {"job_ids": ["arbeitsagentur-a", "arbeitsagentur-b"], "starttermin": "ab sofort"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/batch-tailor",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/x-ndjson")

    events = [json.loads(ln) for ln in resp.read().decode("utf-8").strip().split("\n") if ln.strip()]
    assert events[0] == {"event": "begin", "total": 2}
    assert events[-1] == {"event": "complete", "total": 2}

    starts = [e for e in events if e["event"] == "start"]
    labels = [e for e in events if e["event"] == "label"]
    dones = [e for e in events if e["event"] == "done"]
    assert len(starts) == 2
    assert len(labels) == 2
    assert len(dones) == 2
    # Tailor wurde mit dem richtigen Starttermin gerufen
    assert fake_tailor.call_count == 2
    for call in fake_tailor.call_args_list:
        inp = call.args[0] if call.args else call.kwargs["inp"]
        assert inp.starttermin == "ab sofort"
        assert inp.kontakt_name is None  # Batch laesst Kontakt leer


def test_batch_tailor_skips_already_tailored(running_server, tmp_path, mocker):
    _seed_two_jobs()
    # Job a hat schon tailored_dir
    state = load_state(Paths().state_json)
    state.jobs["arbeitsagentur-a"].tailored_dir = "/tmp/already-there"
    save_state(Paths().state_json, state)

    fake_tailor = mocker.patch("bewerber.tailoring.orchestrator.tailor")
    fake_tailor.return_value = mocker.Mock(output_dir=Path("/tmp/out"))
    mocker.patch("bewerber.shared.llm.LLMClient.for_generation", return_value=mocker.Mock())

    body = {"job_ids": ["arbeitsagentur-a", "arbeitsagentur-b"], "starttermin": "ab sofort"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/batch-tailor",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    events = [json.loads(ln) for ln in resp.read().decode("utf-8").strip().split("\n") if ln.strip()]

    skipped = [e for e in events if e["event"] == "skipped_already_tailored"]
    dones = [e for e in events if e["event"] == "done"]
    assert len(skipped) == 1
    assert skipped[0]["job_id"] == "arbeitsagentur-a"
    assert len(dones) == 1
    assert dones[0]["job_id"] == "arbeitsagentur-b"
    # Tailor nur 1x gerufen
    assert fake_tailor.call_count == 1


def test_batch_tailor_isolates_per_job_errors(running_server, tmp_path, mocker):
    _seed_two_jobs()

    def tail(inp):
        if inp.firma == "Acme":
            raise RuntimeError("LLM quota")
        return mocker.Mock(output_dir=Path("/tmp/out"))

    mocker.patch("bewerber.tailoring.orchestrator.tailor", side_effect=tail)
    mocker.patch("bewerber.shared.llm.LLMClient.for_generation", return_value=mocker.Mock())

    body = {"job_ids": ["arbeitsagentur-a", "arbeitsagentur-b"], "starttermin": "ab sofort"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/batch-tailor",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    events = [json.loads(ln) for ln in resp.read().decode("utf-8").strip().split("\n") if ln.strip()]

    errors = [e for e in events if e["event"] == "error"]
    dones = [e for e in events if e["event"] == "done"]
    assert len(errors) == 1
    assert "LLM quota" in errors[0]["error"]
    assert len(dones) == 1


def test_batch_tailor_rejects_missing_starttermin(running_server):
    code, body = _post_json(running_server, "/api/batch-tailor", {"job_ids": ["x"]})
    assert code == 400


def test_batch_tailor_rejects_empty_job_ids(running_server):
    code, body = _post_json(running_server, "/api/batch-tailor", {"job_ids": [], "starttermin": "x"})
    assert code == 400


def test_batch_tailor_unknown_job_emits_error_event(running_server, tmp_path, mocker):
    _seed_two_jobs()
    mocker.patch("bewerber.shared.llm.LLMClient.for_generation", return_value=mocker.Mock())

    body = {"job_ids": ["does-not-exist"], "starttermin": "ab sofort"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/batch-tailor",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    events = [json.loads(ln) for ln in resp.read().decode("utf-8").strip().split("\n") if ln.strip()]
    errors = [e for e in events if e["event"] == "error"]
    assert len(errors) == 1
    assert "nicht in state.json" in errors[0]["error"]


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


# ---------------------------------------------------------------------------
# Phase 1: Login, Onboarding-Stub, Session-Cookie, Routing
# ---------------------------------------------------------------------------

def test_get_root_without_cookie_redirects_to_login(running_server):
    code, body = _get(running_server, "/", with_session=False)
    assert code == 302
    assert "Location: /login" in body or "REDIRECT to: /login" in body


def test_get_root_with_cookie_but_no_master_profile_redirects_to_onboarding(
    running_server, tmp_path,
):
    """master_profile.yaml entfernen -> Routing schickt auf /onboarding."""
    (tmp_path / "bewerber" / "master_profile.yaml").unlink()
    code, body = _get(running_server, "/", with_session=True)
    assert code == 302
    assert "/onboarding" in body


def test_get_root_with_cookie_and_profile_renders_dashboard(running_server):
    code, body = _get(running_server, "/", with_session=True)
    assert code == 200
    assert "<title>Bewerber-Dashboard</title>" in body
    assert "arbeitsagentur-x1" in body
    # User-Badge sichtbar
    assert "Test User" in body


def test_get_login_page_renders(running_server):
    code, body = _get(running_server, "/login", with_session=False)
    assert code == 200
    assert "Bewerber-Assistent" in body
    assert "Vorname" in body
    assert "Nachname" in body


def test_post_login_sets_session_cookie(running_server):
    """Erfolgreicher Login setzt das Cookie + returnt redirect."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/login",
        data=json.dumps({"vorname": "Erika", "nachname": "Mustermann"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=5)
    assert resp.status == 200
    body = json.loads(resp.read())
    assert body["ok"] is True
    assert body["user"] == "Erika Mustermann"
    assert body["redirect"] == "/"
    set_cookie = resp.getheader("Set-Cookie") or ""
    assert "bewerber_session=Erika%20Mustermann" in set_cookie
    assert "Max-Age=" in set_cookie
    assert "HttpOnly" in set_cookie


def test_post_login_rejects_empty_fields(running_server):
    code, body = _post_json(running_server, "/login", {"vorname": "", "nachname": ""}, with_session=False)
    assert code == 400
    assert "erforderlich" in body["error"]


def test_post_logout_clears_session_cookie(running_server):
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/logout",
        data=b"",
        headers={"Content-Type": "application/json", "Cookie": SESSION_COOKIE},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=5)
    assert resp.status == 200
    body = json.loads(resp.read())
    assert body["redirect"] == "/login"
    set_cookie = resp.getheader("Set-Cookie") or ""
    assert "bewerber_session=" in set_cookie
    assert "Max-Age=0" in set_cookie


def test_get_onboarding_without_cookie_redirects_to_login(running_server):
    code, body = _get(running_server, "/onboarding", with_session=False)
    assert code == 302
    assert "/login" in body


def test_get_onboarding_with_cookie_renders_stub(running_server):
    code, body = _get(running_server, "/onboarding", with_session=True)
    assert code == 200
    assert "Willkommen" in body
    assert "Test User" in body


def test_invalid_session_cookie_treated_as_missing(running_server):
    """Wenn der Cookie da ist aber leer/whitespace, soll der Server so handeln als waere keiner da."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", running_server, timeout=5)
    conn.request("GET", "/", headers={"Cookie": "bewerber_session="})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    assert resp.status == 302
    assert resp.getheader("Location") == "/login"
