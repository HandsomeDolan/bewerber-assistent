"""Tests for the dashboard HTTP server endpoints."""
import json
import threading
import urllib.parse
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


TEST_USER = "tuser"           # make_username("Test", "User")
TEST_PASSWORD = "testpw123"
TEST_SECRET = "test-secret-key"
TEST_INVITE = "let-me-in"


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    """Ephemeral Server mit registriertem Test-User + signierter Session."""
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("BEWERBER_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("BEWERBER_INVITE_CODE", TEST_INVITE)
    (tmp_path / "bewerber").mkdir()
    (tmp_path / "bewerber" / "searches.yaml.example").write_text(
        "defaults: {locations: [L], date_posted_max_days: 14, exclude_keywords: []}\n"
        "searches: [{name: A, keywords: [KI], boards: [arbeitsagentur]}]\n",
    )
    (tmp_path / "bewerber" / "anlagen.yaml.example").write_text("anlagen: []\n")

    from bewerber.dashboard import auth as _auth
    # Test-User registrieren
    registry_path = Paths().users_dir / "registry.json"
    username = _auth.register_user(registry_path, "Test", "User", TEST_PASSWORD)
    assert username == TEST_USER

    # Per-User-Workspace + master_profile-Stub, damit / nicht auf /onboarding umleitet
    up = Paths(user=TEST_USER)
    up.data_dir.mkdir(parents=True, exist_ok=True)
    up.master_profile.write_text(
        "person: {name: x, email: x@y.de}\nberufsprofil: x\nzielposition: []",
    )
    # Ein Seed-Job im User-Workspace
    state = BewerberState(jobs={
        "arbeitsagentur-x1": TrackedJob(raw=RawJob(
            board="arbeitsagentur", external_id="x1",
            url="https://x", title="KI Manager", company="Acme", location="Leipzig",
        )),
    })
    save_state(up.state_json, state)

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


def _signed_cookie() -> str:
    from bewerber.dashboard import auth as _auth
    return "bewerber_session=" + urllib.parse.quote(_auth.sign_session(TEST_USER, TEST_SECRET))


SESSION_COOKIE = None  # wird in _post_json/_get dynamisch erzeugt


def _post_json(port: int, path: str, body: dict, *, with_session: bool = True) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if with_session:
        headers["Cookie"] = _signed_cookie()
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
        headers["Cookie"] = _signed_cookie()

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

    state = load_state(Paths(TEST_USER).state_json)
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
    state = load_state(Paths(TEST_USER).state_json)
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
    up = Paths(user=TEST_USER)
    up.searches_yaml.write_text(yaml.safe_dump({
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
    up = Paths(user=TEST_USER)
    written = yaml.safe_load(up.searches_yaml.read_text())
    assert written["defaults"]["exclude_keywords"] == ["SPS", "PLS"]
    assert written["searches"][0]["name"] == "AI Consulting"
    assert written["searches"][0]["boards"] == ["arbeitsagentur", "linkedin"]

    # No leftover .tmp from the atomic write
    assert not up.searches_yaml.with_suffix(".yaml.tmp").exists()


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
    assert not Paths(user=TEST_USER).searches_yaml.exists()


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
    up = Paths(user=TEST_USER)
    up.anlagen_yaml.write_text(yaml.safe_dump({
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
    up = Paths(user=TEST_USER)
    written = yaml.safe_load(up.anlagen_yaml.read_text())
    assert written["anlagen"][0]["label"] == "Zeugnis"
    assert not up.anlagen_yaml.with_suffix(".yaml.tmp").exists()


def test_post_anlagen_validation_error_returns_400(running_server, tmp_path):
    """Missing required 'label' field -> 400, file unchanged."""
    bad = {"anlagen": [{"files": ["/foo.pdf"]}]}   # no label
    code, body = _post_json(running_server, "/api/anlagen", bad)
    assert code == 400
    assert "label" in body["error"]
    assert not Paths(user=TEST_USER).anlagen_yaml.exists()


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
    Paths(TEST_USER).master_profile.unlink()
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
    save_state(Paths(TEST_USER).state_json, state)

    code, body = _post_json(running_server, "/api/add-posting", {
        "url": "https://dup.example/job", "firma": "X", "rolle": "Y",
    })
    assert code == 409
    assert "bereits erfasst" in body["error"]


def test_add_posting_happy_path(running_server, tmp_path, mocker):
    """Snapshot + Scoring mocked -> state has the new manual job."""
    # Master profile already seeded by fixture in user dir


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
    state = load_state(Paths(TEST_USER).state_json)
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
    save_state(Paths(TEST_USER).state_json, state)

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
    # Master-Profil bereits durch Fixture im User-Workspace vorhanden
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
        headers={"Content-Type": "application/json", "Cookie": _signed_cookie()},
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
    state = load_state(Paths(TEST_USER).state_json)
    manual_jobs = [j for j in state.jobs.values() if j.raw.board == "manual"]
    assert len(manual_jobs) == 2


def test_batch_add_postings_handles_per_url_errors_and_stores_in_failed_urls(
    running_server, tmp_path, mocker,
):
    """Eine URL crasht beim Snapshot -> error-Event + landet in failed_urls."""
    # Master-Profil bereits durch Fixture im User-Workspace vorhanden

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
        headers={"Content-Type": "application/json", "Cookie": _signed_cookie()},
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
    state = load_state(Paths(TEST_USER).state_json)
    assert len(state.failed_urls) == 1
    assert "bad-url" in state.failed_urls[0].url
    assert "snapshot crashed" in state.failed_urls[0].error


def test_batch_add_postings_rejects_empty_urls_list(running_server):
    code, body = _post_json(running_server, "/api/batch-add-postings", {"urls": []})
    assert code == 400


def test_batch_add_postings_rejects_missing_master_profile(running_server, tmp_path):
    """Fixture seeded master_profile.yaml fuer das Routing - hier loeschen,
    damit der Endpoint die fehlende Master-Profile-Pruefung trifft."""
    Paths(TEST_USER).master_profile.unlink()
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
    save_state(Paths(TEST_USER).state_json, state)

    code, body = _post_json(running_server, "/api/failed-urls/clear", {})
    assert code == 200
    assert body["removed"] == 2
    assert load_state(Paths(TEST_USER).state_json).failed_urls == []


def test_failed_urls_remove_drops_one(running_server, tmp_path):
    state = BewerberState(failed_urls=[
        FailedUrl(url="https://a", error="e1", at="2026-06-15T10:00:00"),
        FailedUrl(url="https://b", error="e2", at="2026-06-15T11:00:00"),
    ])
    save_state(Paths(TEST_USER).state_json, state)

    code, body = _post_json(running_server, "/api/failed-urls/remove", {"url": "https://a"})
    assert code == 200
    after = load_state(Paths(TEST_USER).state_json).failed_urls
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

    state = load_state(Paths(TEST_USER).state_json)
    assert state.jobs["arbeitsagentur-x1"].notes == "Frei-Text\nMehrere Zeilen."


def test_notes_set_overwrites_prior_notes(running_server):
    # First set
    _post_json(running_server, "/api/notes-set", {"job_id": "arbeitsagentur-x1", "notes": "alt"})
    # Then replace
    code, _ = _post_json(running_server, "/api/notes-set", {"job_id": "arbeitsagentur-x1", "notes": "neu"})
    assert code == 200
    assert load_state(Paths(TEST_USER).state_json).jobs["arbeitsagentur-x1"].notes == "neu"


def test_notes_set_allows_empty_string_to_clear_notes(running_server):
    """Notes loeschen indem man leeren String sendet."""
    _post_json(running_server, "/api/notes-set", {"job_id": "arbeitsagentur-x1", "notes": "was"})
    code, _ = _post_json(running_server, "/api/notes-set", {"job_id": "arbeitsagentur-x1", "notes": ""})
    assert code == 200
    assert load_state(Paths(TEST_USER).state_json).jobs["arbeitsagentur-x1"].notes == ""


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
    save_state(Paths(TEST_USER).state_json, state)


def test_batch_tailor_streams_ndjson_per_job(running_server, tmp_path, mocker):
    _seed_two_jobs()
    fake_tailor = mocker.patch("bewerber.tailoring.orchestrator.tailor")
    fake_tailor.return_value = mocker.Mock(output_dir=Path("/tmp/out"))
    mocker.patch("bewerber.shared.llm.LLMClient.for_generation", return_value=mocker.Mock())

    body = {"job_ids": ["arbeitsagentur-a", "arbeitsagentur-b"], "starttermin": "ab sofort"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/batch-tailor",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Cookie": _signed_cookie()},
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
    state = load_state(Paths(TEST_USER).state_json)
    state.jobs["arbeitsagentur-a"].tailored_dir = "/tmp/already-there"
    save_state(Paths(TEST_USER).state_json, state)

    fake_tailor = mocker.patch("bewerber.tailoring.orchestrator.tailor")
    fake_tailor.return_value = mocker.Mock(output_dir=Path("/tmp/out"))
    mocker.patch("bewerber.shared.llm.LLMClient.for_generation", return_value=mocker.Mock())

    body = {"job_ids": ["arbeitsagentur-a", "arbeitsagentur-b"], "starttermin": "ab sofort"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/batch-tailor",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Cookie": _signed_cookie()},
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
        headers={"Content-Type": "application/json", "Cookie": _signed_cookie()},
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
        headers={"Content-Type": "application/json", "Cookie": _signed_cookie()},
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
    save_state(Paths(TEST_USER).state_json, state)

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
# Briefing-Endpoint
# ---------------------------------------------------------------------------

def test_briefing_rejects_unknown_job(running_server):
    code, body = _post_json(running_server, "/api/briefing", {"job_id": "ghost-9999"})
    assert code == 404


def test_briefing_rejects_job_without_tailored_dir(running_server, tmp_path):
    from bewerber.shared.state_schema import Scoring as _Sc
    state = BewerberState(jobs={
        "x-1": TrackedJob(raw=RawJob(
            board="x", external_id="1", url="https://x", title="t", company="c",
            location="l", description="d",
        ), scoring=_Sc(fit_score=7, begruendung="x", matched_skills=[],
                       missing_skills=[], red_flags=[], verbessern_in_anschreiben=[])),
    })
    save_state(Paths(TEST_USER).state_json, state)
    code, body = _post_json(running_server, "/api/briefing", {"job_id": "x-1"})
    assert code == 400
    assert "tailored_dir" in body["error"]


def test_briefing_happy_path_writes_pdf_to_briefing_subdir(running_server, tmp_path, mocker):
    """Happy path: LLM gemockt, PDF wird im <tailored_dir>/briefing/ abgelegt."""
    from bewerber.shared.state_schema import Scoring as _Sc
    from bewerber.briefing import InterviewBriefingContent, ProfileFramingEntry, QAEntry, AskedQuestionEntry

    # Tailored-Dir vorbereiten
    tailored = tmp_path / "bewerbungs-out"
    tailored.mkdir()

    state = BewerberState(jobs={
        "x-1": TrackedJob(
            raw=RawJob(
                board="x", external_id="1", url="https://x",
                title="AI Consultant", company="Acme GmbH",
                location="Leipzig", description="Wir suchen einen AI-Consultant ...",
            ),
            scoring=_Sc(fit_score=7, begruendung="ok",
                        matched_skills=["Python", "n8n"], missing_skills=["ITIL"],
                        red_flags=["Befristet"], verbessern_in_anschreiben=[]),
            tailored_dir=str(tailored),
        ),
    })
    save_state(Paths(TEST_USER).state_json, state)

    fake_briefing = InterviewBriefingContent(
        company_overview="Acme ist ein KI-Consultancy.",
        company_facts=["Sitz Leipzig", "50 MA"],
        methodik_und_tonalitaet=["Pragmatisch", "Wertorientiert"],
        role_summary="Du beraetst Kunden bei KI-Use-Cases.",
        role_does=["Workshops moderieren"],
        role_doesnt=["Selbst entwickeln"],
        profile_framing=[
            ProfileFramingEntry(anforderung="n8n-Erfahrung", match_aus_profil="n8n bei IC Music seit 2026"),
        ],
        expected_questions=[
            QAEntry(frage="Warum Acme?", antwort="Drei Gruende. Erstens passt der Ansatz..."),
        ],
        questions_to_ask=[
            AskedQuestionEntry(frage="Wie sind die Teams aufgestellt?", warum="Senior-Lead verstehen"),
        ],
        salary_advice="Range 65-85k brutto.",
        closing_statement="Spannende Position, ich freue mich auf Ihre Rueckmeldung.",
        red_flags=["Befristet"],
        sprechstil_tips=["Konkrete Zahlen nennen"],
    )
    mocker.patch("bewerber.briefing.generate_briefing", return_value=fake_briefing)
    mocker.patch("bewerber.shared.llm.LLMClient.for_scoring", return_value=mocker.Mock())

    code, body = _post_json(running_server, "/api/briefing", {"job_id": "x-1"})
    assert code == 200, body
    assert body["ok"] is True
    pdf_path = Path(body["pdf_path"])
    assert pdf_path.is_file()
    assert pdf_path.parent.name == "briefing"
    assert pdf_path.parent.parent == tailored
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_briefing_llm_failure_returns_502(running_server, tmp_path, mocker):
    from bewerber.shared.state_schema import Scoring as _Sc
    tailored = tmp_path / "out"; tailored.mkdir()
    state = BewerberState(jobs={
        "x-1": TrackedJob(
            raw=RawJob(board="x", external_id="1", url="", title="t",
                       company="c", location="l", description="d"),
            scoring=_Sc(fit_score=5, begruendung="x", matched_skills=[],
                        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[]),
            tailored_dir=str(tailored),
        ),
    })
    save_state(Paths(TEST_USER).state_json, state)
    mocker.patch("bewerber.briefing.generate_briefing", side_effect=RuntimeError("LLM down"))
    mocker.patch("bewerber.shared.llm.LLMClient.for_scoring", return_value=mocker.Mock())

    code, body = _post_json(running_server, "/api/briefing", {"job_id": "x-1"})
    assert code == 502
    assert "LLM down" in body["error"]


# ---------------------------------------------------------------------------
# Discover-Run-Endpoint
# ---------------------------------------------------------------------------

def test_discover_run_starts_background_thread(running_server, tmp_path, mocker):
    # searches.yaml anlegen
    import yaml
    (tmp_path / "bewerber" / "searches.yaml").write_text(yaml.safe_dump({
        "defaults": {"locations": ["L"], "date_posted_max_days": 14, "exclude_keywords": []},
        "searches": [{"name": "A", "keywords": ["KI"], "boards": ["arbeitsagentur"]}],
    }))
    # Discover-Hintergrundlauf komplett mocken
    mocker.patch("bewerber.dashboard.server._run_discover_background", autospec=True)

    code, body = _post_json(running_server, "/api/discover/run", {})
    assert code == 200
    assert body["ok"] is True
    assert "job_id" in body


def test_discover_run_rejects_concurrent_runs(running_server, tmp_path, mocker):
    """Zwei Aufrufe in Folge -> zweiter bekommt 409."""
    from bewerber.dashboard import server as srv
    # Manuell einen "laufenden" Job ins State injizieren
    with srv._discover_lock:
        srv._discover_state["current_id"] = "already-running"
        srv._discover_state["jobs"]["already-running"] = {"status": "running"}

    code, body = _post_json(running_server, "/api/discover/run", {})
    assert code == 409
    assert body["current_job_id"] == "already-running"

    # Aufraeumen
    with srv._discover_lock:
        srv._discover_state["current_id"] = None


def test_discover_status_returns_idle_when_nothing_running(running_server):
    from bewerber.dashboard import server as srv
    with srv._discover_lock:
        srv._discover_state["current_id"] = None
        srv._discover_state["jobs"].clear()
    code, body = _get(running_server, "/api/discover/status")
    assert code == 200
    assert json.loads(body)["status"] == "idle"


def test_discover_status_returns_done_with_summary(running_server):
    from bewerber.dashboard import server as srv
    with srv._discover_lock:
        srv._discover_state["jobs"]["done-job"] = {
            "status": "done",
            "started_at": "2026-06-19T10:00",
            "finished_at": "2026-06-19T10:05",
            "new_jobs": 3,
            "total_jobs": 12,
            "scrape_errors": {},
        }
    code, body = _get(running_server, "/api/discover/status?job_id=done-job")
    assert code == 200
    data = json.loads(body)
    assert data["status"] == "done"
    assert data["new_jobs"] == 3


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
    Paths(TEST_USER).master_profile.unlink()
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
    assert "Username" in body
    assert "Passwort" in body


def test_login_page_has_register_toggle(running_server):
    code, html = _get(running_server, "/login", with_session=False)
    assert code == 200
    assert 'id="register-form"' in html
    assert 'id="login-form"' in html
    assert "Einladungs-Code" in html


def test_post_login_sets_session_cookie(running_server):
    code, body = _post_json(
        running_server, "/login",
        {"username": TEST_USER, "passwort": TEST_PASSWORD},
        with_session=False,
    )
    assert code == 200
    assert body["redirect"] == "/"


def test_post_login_rejects_empty_fields(running_server):
    code, body = _post_json(running_server, "/login", {"username": "", "passwort": ""}, with_session=False)
    assert code == 400
    assert "erforderlich" in body["error"]


def test_post_login_rejects_wrong_password(running_server):
    code, body = _post_json(
        running_server, "/login",
        {"username": TEST_USER, "passwort": "falsch"},
        with_session=False,
    )
    assert code == 401


def test_post_logout_clears_session_cookie(running_server):
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/logout",
        data=b"",
        headers={"Content-Type": "application/json", "Cookie": _signed_cookie()},
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
    assert "Onboarding" in body
    assert "Test User" in body
    assert "Step 1: Profil aus Dokumenten erstellen" in body


# ---------------------------------------------------------------------------
# Phase 2: Onboarding-Extraction (Upload + Background-Thread + Status-Poll)
# ---------------------------------------------------------------------------

def test_parse_multipart_single_file_field():
    """Smoke-Test fuer den selbstgeschriebenen Multipart-Parser."""
    from bewerber.dashboard.server import _parse_multipart
    boundary = "----testboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="lebenslauf.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "%PDF-1.4 dummy\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    fields = _parse_multipart({"Content-Type": f"multipart/form-data; boundary={boundary}"}, body)
    assert "files" in fields
    assert len(fields["files"]) == 1
    content, fname = fields["files"][0]
    assert fname == "lebenslauf.pdf"
    assert content == b"%PDF-1.4 dummy"


def test_parse_multipart_two_file_fields_same_name():
    """Mehrere Files unter dem gleichen Form-Feldnamen 'files'."""
    from bewerber.dashboard.server import _parse_multipart
    boundary = "----b"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="a.pdf"\r\n\r\n'
        "AAA\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="b.pdf"\r\n\r\n'
        "BBB\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    fields = _parse_multipart({"Content-Type": f"multipart/form-data; boundary={boundary}"}, body)
    assert len(fields["files"]) == 2
    assert {fn for _, fn in fields["files"]} == {"a.pdf", "b.pdf"}


def test_onboarding_extract_starts_background_job_returns_job_id(running_server, tmp_path, mocker):
    """Upload-Happy-Path: Files landen in einem temp-Dir, Thread startet, job_id wird returnt."""
    from bewerber.dashboard import server as srv

    # Background-Thread soll NICHT echt extrahieren - sofort 'done' melden
    def fake_run(job_id, upload_dir, paths):
        with srv._onboarding_lock:
            srv._onboarding_jobs[job_id] = {
                "status": "done",
                "started_at": "2026-06-16T12:00",
                "summary": {"name": "Test User", "stellen": 1, "ausbildung": 0, "sprachen": 1},
                "master_profile_path": str(paths.master_profile),
            }
    mocker.patch("bewerber.dashboard.server._run_onboarding_extraction", side_effect=fake_run)

    # Multipart-Body manuell bauen
    boundary = "----py-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="lebenslauf.pdf"\r\n\r\n'
        "%PDF dummy\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/onboarding/extract",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Cookie": _signed_cookie(),
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=5)
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data["ok"] is True
    assert "job_id" in data
    assert data["files"] == ["lebenslauf.pdf"]


def test_onboarding_extract_rejects_request_without_files(running_server, mocker):
    """Multipart-Body, aber kein 'files'-Feld -> 400."""
    boundary = "----py-test-empty"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="other"\r\n\r\n'
        "not-a-file\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/onboarding/extract",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Cookie": _signed_cookie(),
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_onboarding_extract_requires_login(running_server):
    """Ohne Cookie -> 401."""
    boundary = "----b"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="x.pdf"\r\n\r\n'
        "x\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/onboarding/extract",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("expected 401")
    except urllib.error.HTTPError as e:
        assert e.code == 401


def test_onboarding_status_returns_running_state(running_server):
    """Ohne dass jemals ein Job lief: explizit einen running-Job setzen + polling."""
    from bewerber.dashboard import server as srv
    with srv._onboarding_lock:
        srv._onboarding_jobs["abc123"] = {"status": "running", "started_at": "2026-06-16T12:00"}
    code, body = _get(running_server, "/api/onboarding/status?job_id=abc123")
    assert code == 200
    data = json.loads(body)
    assert data["status"] == "running"


def test_onboarding_status_returns_done_with_summary(running_server):
    from bewerber.dashboard import server as srv
    with srv._onboarding_lock:
        srv._onboarding_jobs["done-job"] = {
            "status": "done", "started_at": "2026-06-16T12:00",
            "summary": {"name": "Steve", "stellen": 3, "ausbildung": 2, "sprachen": 1},
            "master_profile_path": "/some/path",
        }
    code, body = _get(running_server, "/api/onboarding/status?job_id=done-job")
    assert code == 200
    data = json.loads(body)
    assert data["status"] == "done"
    assert data["summary"]["name"] == "Steve"


def test_onboarding_status_unknown_job_returns_404(running_server):
    code, body = _get(running_server, "/api/onboarding/status?job_id=ghost-9999")
    assert code == 404


def test_onboarding_status_missing_job_id_returns_400(running_server):
    code, body = _get(running_server, "/api/onboarding/status")
    assert code == 400


def test_run_onboarding_extraction_writes_master_profile_yaml(tmp_path, mocker, monkeypatch):
    """Background-Worker integration: bei Erfolg landet master_profile.yaml + summary."""
    from bewerber.dashboard import server as srv
    from bewerber.profile.extractor import ExtractedProfile
    from bewerber.shared.profile_schema import Person, Berufserfahrung, Sprache, Ausbildung

    fake_profile = ExtractedProfile(
        person=Person(name="Erika Mustermann", email="e@m.de"),
        berufsprofil="x",
        zielposition=[],
        ausbildung=[Ausbildung(art="Studium", institution="TU", abschluss="B.Sc.")],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01", aufgaben=["a"], erfolge=[], skills=["Python"]),
        ],
        sprachen=[Sprache(sprache="Deutsch", niveau="C2")],
    )
    mocker.patch(
        "bewerber.profile.extractor.extract_profile_from_documents",
        return_value=fake_profile,
    )
    mocker.patch("bewerber.shared.llm.LLMClient.for_scoring", return_value=mocker.Mock())

    # Eigener isolierter Workspace (zusaetzlich zum conftest-Guard, macht die
    # Absicht explizit): NIEMALS gegen den echten Workspace schreiben.
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path / "ws"))
    paths = Paths()
    paths.bewerber_dir.mkdir(parents=True, exist_ok=True)
    # frisch: kein master_profile.yaml vorhanden -> Worker legt es an
    assert not paths.master_profile.exists()

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    (upload_dir / "dummy.pdf").write_bytes(b"%PDF dummy")

    job_id = "test-job"
    with srv._onboarding_lock:
        srv._onboarding_jobs[job_id] = {"status": "running"}
    srv._run_onboarding_extraction(job_id, upload_dir, paths)

    # State: done
    with srv._onboarding_lock:
        state = srv._onboarding_jobs[job_id]
    assert state["status"] == "done"
    assert state["summary"]["name"] == "Erika Mustermann"
    assert state["summary"]["stellen"] == 1
    # Datei geschrieben
    assert paths.master_profile.is_file()
    import yaml as _yaml
    loaded = _yaml.safe_load(paths.master_profile.read_text())
    assert loaded["person"]["name"] == "Erika Mustermann"
    assert loaded["projekte"] == []   # projekte werden NICHT vom Extraktor befuellt


def test_run_onboarding_extraction_records_failure(tmp_path, mocker):
    """Wenn extract_profile_from_documents wirft: status='failed' + error-Message."""
    from bewerber.dashboard import server as srv
    mocker.patch(
        "bewerber.profile.extractor.extract_profile_from_documents",
        side_effect=RuntimeError("LLM quota exhausted"),
    )
    mocker.patch("bewerber.shared.llm.LLMClient.for_scoring", return_value=mocker.Mock())

    paths = Paths()
    paths.bewerber_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = tmp_path / "u"; upload_dir.mkdir()

    job_id = "fail-job"
    with srv._onboarding_lock:
        srv._onboarding_jobs[job_id] = {"status": "running"}
    srv._run_onboarding_extraction(job_id, upload_dir, paths)

    with srv._onboarding_lock:
        state = srv._onboarding_jobs[job_id]
    assert state["status"] == "failed"
    assert "LLM quota" in state["error"]


# ---------------------------------------------------------------------------
# Phase 3: Onboarding Steps 2-4 (Scan-Folder, Save)
# ---------------------------------------------------------------------------

def test_onboarding_scan_folder_lists_files(running_server, tmp_path):
    folder = tmp_path / "anlagen-src"
    folder.mkdir()
    (folder / "Zeugnis.pdf").write_bytes(b"%PDF dummy")
    (folder / "Urkunde.pdf").write_bytes(b"%PDF dummy 2")
    (folder / ".DS_Store").write_bytes(b"x")  # versteckte Files werden gefiltert
    code, body = _post_json(running_server, "/api/onboarding/scan-folder", {"path": str(folder)})
    assert code == 200
    names = [f["name"] for f in body["files"]]
    assert names == ["Urkunde.pdf", "Zeugnis.pdf"]   # sorted, ohne .DS_Store


def test_onboarding_scan_folder_404_when_path_missing(running_server, tmp_path):
    code, body = _post_json(running_server, "/api/onboarding/scan-folder", {
        "path": str(tmp_path / "does-not-exist"),
    })
    assert code == 404


def test_onboarding_scan_folder_400_when_path_empty(running_server):
    code, body = _post_json(running_server, "/api/onboarding/scan-folder", {"path": ""})
    assert code == 400


def test_onboarding_save_writes_searches_yaml(running_server, tmp_path):
    code, body = _post_json(running_server, "/api/onboarding/save", {
        "searches": {"keywords": ["KI Manager", "Lead PM"], "boards": ["arbeitsagentur", "linkedin"]},
        "defaults": {"locations": ["Leipzig", "Remote"], "date_posted_max_days": 21, "exclude_keywords": ["SPS"]},
        "anlagen_folder": None,
        "anschreiben_examples": [],
        "extraction_job_id": None,
    })
    assert code == 200, body
    assert body["ok"] is True
    assert body["redirect"] == "/"

    # searches.yaml geschrieben
    import yaml
    written = yaml.safe_load(Paths(user=TEST_USER).searches_yaml.read_text())
    assert written["defaults"]["locations"] == ["Leipzig", "Remote"]
    assert written["defaults"]["date_posted_max_days"] == 21
    assert written["defaults"]["exclude_keywords"] == ["SPS"]
    assert len(written["searches"]) == 1
    assert written["searches"][0]["name"] == "Standard"
    assert written["searches"][0]["keywords"] == ["KI Manager", "Lead PM"]
    assert written["searches"][0]["boards"] == ["arbeitsagentur", "linkedin"]


def test_onboarding_save_writes_anlagen_yaml_from_folder(running_server, tmp_path):
    """anlagen_folder mit PDFs -> anlagen.yaml mit einer Anlage pro File."""
    folder = tmp_path / "anlagen-src"
    folder.mkdir()
    (folder / "Arbeitszeugnis.pdf").write_bytes(b"%PDF a")
    (folder / "REFA_Urkunde.pdf").write_bytes(b"%PDF b")
    (folder / "image.jpg").write_bytes(b"\xff\xd8\xff img")

    code, body = _post_json(running_server, "/api/onboarding/save", {
        "searches": {"keywords": ["x"], "boards": ["arbeitsagentur"]},
        "defaults": {"locations": ["Leipzig"], "date_posted_max_days": 14, "exclude_keywords": []},
        "anlagen_folder": str(folder),
        "anschreiben_examples": [],
        "extraction_job_id": None,
    })
    assert code == 200, body
    assert body["summary"]["anlagen"] == 3   # 2 PDFs + 1 JPG

    import yaml
    written = yaml.safe_load(Paths(user=TEST_USER).anlagen_yaml.read_text())
    labels = [a["label"] for a in written["anlagen"]]
    assert "Arbeitszeugnis" in labels
    assert "REFA_Urkunde" in labels


def test_onboarding_save_writes_anschreiben_examples_from_upload_dir(running_server, tmp_path):
    """Anschreiben-Stil-Beispiele werden aus dem Upload-Dir kopiert (text-Extraktion)."""
    from bewerber.dashboard import server as srv
    # Upload-Dir mit zwei "Anschreiben"-Dateien anlegen
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    # save_anschreiben_examples liest Text aus den Files. .txt geht durch ohne PDF-Parser.
    # (Wir koennen aber save_anschreiben_examples mocken)
    (upload_dir / "anschreiben1.pdf").write_bytes(b"%PDF dummy")
    (upload_dir / "anschreiben2.pdf").write_bytes(b"%PDF dummy 2")
    (upload_dir / "lebenslauf.pdf").write_bytes(b"%PDF cv")

    # Fake Job-State so anlegen, als waere Step 1 fertig
    job_id = "saved-job"
    with srv._onboarding_lock:
        srv._onboarding_jobs[job_id] = {
            "status": "done",
            "upload_dir": str(upload_dir),
            "files": ["anschreiben1.pdf", "anschreiben2.pdf", "lebenslauf.pdf"],
        }

    # save_anschreiben_examples patchen (echte Implementierung liest PDF-Text)
    from unittest.mock import patch
    fake_paths = [tmp_path / "examples" / "01_x.txt", tmp_path / "examples" / "02_y.txt"]
    with patch(
        "bewerber.profile.extractor.save_anschreiben_examples",
        return_value=fake_paths,
    ) as mock_save:
        code, body = _post_json(running_server, "/api/onboarding/save", {
            "searches": {"keywords": ["x"], "boards": ["arbeitsagentur"]},
            "defaults": {"locations": ["Leipzig"], "date_posted_max_days": 14, "exclude_keywords": []},
            "anlagen_folder": None,
            "anschreiben_examples": ["anschreiben1.pdf", "anschreiben2.pdf"],
            "extraction_job_id": job_id,
        })
    assert code == 200
    assert body["summary"]["anschreiben_examples"] == 2
    # save_anschreiben_examples wurde mit den 2 ausgewaehlten Pfaden gerufen
    args, kwargs = mock_save.call_args
    selected_paths = args[0]
    assert len(selected_paths) == 2
    assert all("anschreiben" in p.name for p in selected_paths)


def test_onboarding_save_rejects_empty_keywords(running_server):
    code, body = _post_json(running_server, "/api/onboarding/save", {
        "searches": {"keywords": [], "boards": ["arbeitsagentur"]},
        "defaults": {"locations": ["Leipzig"], "date_posted_max_days": 14, "exclude_keywords": []},
    })
    assert code == 400
    assert "Suchbegriff" in body["error"]


def test_onboarding_save_rejects_empty_locations(running_server):
    code, body = _post_json(running_server, "/api/onboarding/save", {
        "searches": {"keywords": ["KI"], "boards": ["arbeitsagentur"]},
        "defaults": {"locations": [], "date_posted_max_days": 14, "exclude_keywords": []},
    })
    assert code == 400
    assert "Location" in body["error"]


def test_onboarding_save_requires_login(running_server):
    code, body = _post_json(running_server, "/api/onboarding/save", {
        "searches": {"keywords": ["x"]}, "defaults": {"locations": ["x"]},
    }, with_session=False)
    assert code == 401


def test_invalid_session_cookie_treated_as_missing(running_server):
    """Wenn der Cookie da ist aber leer/whitespace, soll der Server so handeln als waere keiner da."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", running_server, timeout=5)
    conn.request("GET", "/", headers={"Cookie": "bewerber_session=garbage"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    assert resp.status == 302
    assert resp.getheader("Location") == "/login"


# ---------------------------------------------------------------------------
# Register-Endpoint + Daten-Isolation
# ---------------------------------------------------------------------------

def test_register_happy_path_creates_user_and_workspace(running_server):
    code, body = _post_json(
        running_server, "/api/register",
        {"vorname": "Neu", "nachname": "Kandidat", "passwort": "geheimpw1", "invite_code": TEST_INVITE},
        with_session=False,
    )
    assert code == 200, body
    assert body["username"] == "nkandidat"
    up = Paths(user="nkandidat")
    assert up.data_dir.is_dir()
    assert up.searches_yaml.is_file()  # aus .example kopiert


def test_register_wrong_invite_code_rejected(running_server):
    code, body = _post_json(
        running_server, "/api/register",
        {"vorname": "X", "nachname": "Y", "passwort": "geheimpw1", "invite_code": "falsch"},
        with_session=False,
    )
    assert code == 403


def test_register_short_password_rejected(running_server):
    code, body = _post_json(
        running_server, "/api/register",
        {"vorname": "X", "nachname": "Y", "passwort": "kurz", "invite_code": TEST_INVITE},
        with_session=False,
    )
    assert code == 400


def test_data_isolation_between_users(running_server):
    """Bea hat ihr eigenes master_profile + einen eigenen Job (Globex Bea).
    Ihr Dashboard muss IHREN Job zeigen und NICHT tusers 'Acme'."""
    from bewerber.dashboard import auth as _auth

    # --- Bea registrieren ---
    code, body = _post_json(
        running_server, "/api/register",
        {"vorname": "Bea", "nachname": "Beispiel", "passwort": "geheimpw1", "invite_code": TEST_INVITE},
        with_session=False,
    )
    assert code == 200
    bea_username = body["username"]
    bea_cookie = "bewerber_session=" + urllib.parse.quote(_auth.sign_session(bea_username, TEST_SECRET))

    # --- Beas eigenes master_profile anlegen (gleicher Stub wie tuser-Fixture) ---
    bea_paths = Paths(user=bea_username)
    bea_paths.master_profile.write_text(
        "person: {name: Bea Beispiel, email: bea@example.de}\nberufsprofil: x\nzielposition: []",
    )

    # --- Bea bekommt einen eigenen Seed-Job in ihrer state.json ---
    bea_state = BewerberState(jobs={
        "arbeitsagentur-bea1": TrackedJob(raw=RawJob(
            board="arbeitsagentur", external_id="bea1",
            url="https://globex.bea/job", title="Data Analyst", company="Globex Bea",
            location="Berlin",
        )),
    })
    save_state(bea_paths.state_json, bea_state)

    # --- Beas Dashboard GET / ---
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/",
        headers={"Cookie": bea_cookie},
    )
    resp = urllib.request.urlopen(req, timeout=5)
    body_bytes = resp.read()

    # Bea sieht ihren Job, aber NICHT tusers "Acme"
    assert b"Globex Bea" in body_bytes, "Beas eigener Job fehlt im Dashboard"
    assert b"Acme" not in body_bytes, "tusers 'Acme'-Job darf in Beas Dashboard nicht auftauchen"


def test_post_data_route_requires_session(running_server):
    """POST /api/mark ohne Session-Cookie muss 401 zurueckgeben.
    Sichert, dass der zentrale Guard in do_POST greift."""
    code, body = _post_json(
        running_server,
        "/api/mark",
        {"job_id": "arbeitsagentur-x1", "status": "applied"},
        with_session=False,
    )
    assert code == 401, f"Erwartet 401, bekam {code}: {body}"
    assert "eingeloggt" in body.get("error", "").lower() or "nicht" in body.get("error", "").lower()


# ---------------------------------------------------------------------------
# Anlagen-Upload-Endpoint
# ---------------------------------------------------------------------------

def test_anlagen_upload_saves_to_user_dir(running_server):
    import urllib.request
    boundary = "----testboundary"
    parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="zeugnis.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "PDFDATA\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/anlagen/upload",
        data=parts,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Cookie": _signed_cookie()},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=5)
    body = json.loads(resp.read())
    assert body["ok"] is True
    assert body["saved"] == ["anlagen/zeugnis.pdf"]
    up = Paths(user=TEST_USER)
    assert (up.data_dir / "anlagen" / "zeugnis.pdf").is_file()


def test_anlagen_upload_requires_session(running_server):
    code, body = _post_json(running_server, "/api/anlagen/upload", {}, with_session=False)
    assert code == 401


# ---------------------------------------------------------------------------
# Download-Endpoints: /api/job-files, /api/download, /api/download-zip
# ---------------------------------------------------------------------------

def _seed_tailored_job(jid="arbeitsagentur-dl1"):
    """Legt einen Job mit tailored_dir + zwei Dateien im User-Workspace an."""
    up = Paths(user=TEST_USER)
    td = up.bewerbungen / "2026-06-20_Acme_Dev"
    td.mkdir(parents=True, exist_ok=True)
    (td / "lebenslauf.pdf").write_bytes(b"%PDF-CV")
    (td / "anschreiben.pdf").write_bytes(b"%PDF-AN")
    state = load_state(up.state_json)
    from bewerber.shared.state_schema import RawJob, TrackedJob
    state.jobs[jid] = TrackedJob(
        raw=RawJob(board="arbeitsagentur", external_id="dl1", url="u",
                   title="Dev", company="Acme", location="L"),
        tailored_dir=str(td),
    )
    save_state(up.state_json, state)
    return jid, td


def test_job_files_lists_user_files(running_server):
    jid, td = _seed_tailored_job()
    code, body = _get(running_server, f"/api/job-files?job_id={jid}")
    assert code == 200
    names = {f["name"] for f in json.loads(body)["files"]}
    assert {"lebenslauf.pdf", "anschreiben.pdf"} <= names


def test_download_streams_file(running_server):
    jid, td = _seed_tailored_job()
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/download?job_id={jid}&file=lebenslauf.pdf",
        headers={"Cookie": _signed_cookie()},
    )
    resp = urllib.request.urlopen(req, timeout=5)
    assert resp.read() == b"%PDF-CV"


def test_download_blocks_path_traversal(running_server):
    jid, td = _seed_tailored_job()
    code, body = _get(running_server, f"/api/download?job_id={jid}&file=../../../etc/passwd")
    assert code == 400


def test_download_unknown_job_404(running_server):
    code, body = _get(running_server, "/api/download?job_id=does-not-exist&file=x.pdf")
    assert code == 404


def test_download_requires_session(running_server):
    jid, td = _seed_tailored_job()
    code, body = _get(running_server, f"/api/job-files?job_id={jid}", with_session=False)
    assert code == 401


def test_download_zip_contains_files(running_server):
    import io, zipfile, urllib.request
    jid, td = _seed_tailored_job()
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/download-zip?job_id={jid}",
        headers={"Cookie": _signed_cookie()},
    )
    resp = urllib.request.urlopen(req, timeout=5)
    zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    assert "lebenslauf.pdf" in zf.namelist()


def test_download_zip_excludes_symlinks(running_server):
    import io, zipfile, urllib.request, os
    jid, td = _seed_tailored_job("arbeitsagentur-sym1")
    # plant a symlink inside the tailored dir pointing outside
    secret = td.parent / "secret.txt"
    secret.write_text("TOPSECRET")
    try:
        os.symlink(secret, td / "leak.txt")
    except (OSError, NotImplementedError):
        import pytest; pytest.skip("symlinks not supported")
    req = urllib.request.Request(
        f"http://127.0.0.1:{running_server}/api/download-zip?job_id={jid}",
        headers={"Cookie": _signed_cookie()},
    )
    resp = urllib.request.urlopen(req, timeout=5)
    zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    assert "leak.txt" not in zf.namelist()


def test_dashboard_uses_download_not_fileurl(running_server):
    code, html = _get(running_server, "/")
    assert code == 200
    assert "/api/download-zip?job_id=" in html
    # Keine file://-Links mehr (funktionieren remote nicht)
    assert "file://" not in html


def test_is_deliverable_filters_internal_and_posting_files():
    from bewerber.dashboard.server import _is_deliverable
    # behalten
    assert _is_deliverable("lebenslauf.pdf")
    assert _is_deliverable("anschreiben.pdf")
    assert _is_deliverable("Arbeitszeugnis_Magna_Eigenwillig.pdf")
    # raus: interne Quell-/Log-Dateien
    assert not _is_deliverable("anschreiben.md")
    assert not _is_deliverable("lebenslauf.html")
    assert not _is_deliverable("tailoring_log.json")
    assert not _is_deliverable("posting_meta.yaml")
    # raus: posting.* (egal welche Endung)
    assert not _is_deliverable("posting.txt")
    assert not _is_deliverable("posting.pdf")
    assert not _is_deliverable("posting.html")


def test_job_files_excludes_internal_files(running_server):
    """job-files listet nur Deliverables (keine .md/.html/.json/.yaml/posting.*)."""
    from bewerber.shared.paths import Paths
    up = Paths(user=TEST_USER)
    job_dir = up.bewerbungen / "2026-06-20_Acme_Dev"
    job_dir.mkdir(parents=True, exist_ok=True)
    for name in ["lebenslauf.pdf", "anschreiben.pdf", "anschreiben.md",
                 "lebenslauf.html", "tailoring_log.json", "posting_meta.yaml",
                 "posting.txt", "posting.pdf", "Zeugnis.pdf"]:
        (job_dir / name).write_text("x")

    state = load_state(up.state_json)
    state.jobs["arbeitsagentur-x1"].tailored_dir = str(job_dir)
    save_state(up.state_json, state)

    code, body = _get(running_server, "/api/job-files?job_id=arbeitsagentur-x1")
    assert code == 200
    names = {f["name"] for f in json.loads(body)["files"]}
    assert names == {"lebenslauf.pdf", "anschreiben.pdf", "Zeugnis.pdf"}


def test_delete_job_removes_entry_and_dir_within_bewerbungen(running_server):
    from bewerber.shared.paths import Paths
    up = Paths(user=TEST_USER)
    job_dir = up.bewerbungen / "2026-06-20_Acme_Dev"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "lebenslauf.pdf").write_text("x")

    state = load_state(up.state_json)
    state.jobs["arbeitsagentur-x1"].tailored_dir = str(job_dir)
    save_state(up.state_json, state)

    code, data = _post_json(running_server, "/api/delete-job", {"job_id": "arbeitsagentur-x1"})
    assert code == 200
    assert data["ok"] and data["dir_deleted"] is True
    assert not job_dir.exists()
    assert "arbeitsagentur-x1" not in load_state(up.state_json).jobs


def test_delete_job_keeps_dir_outside_bewerbungen(running_server, tmp_path):
    from bewerber.shared.paths import Paths
    up = Paths(user=TEST_USER)
    outside = tmp_path / "fremd"
    outside.mkdir()
    (outside / "wichtig.pdf").write_text("x")

    state = load_state(up.state_json)
    state.jobs["arbeitsagentur-x1"].tailored_dir = str(outside)
    save_state(up.state_json, state)

    code, data = _post_json(running_server, "/api/delete-job", {"job_id": "arbeitsagentur-x1"})
    assert code == 200
    assert data["ok"] and data["dir_deleted"] is False
    assert outside.exists()  # ausserhalb Bewerbungen/ -> NICHT geloescht
    assert "arbeitsagentur-x1" not in load_state(up.state_json).jobs


def test_dashboard_contains_delete_function(running_server):
    code, body = _get(running_server, "/")
    assert code == 200
    assert "deleteJob" in body
    assert "/api/delete-job" in body


def test_dashboard_contains_kanban_view(running_server):
    code, body = _get(running_server, "/")
    assert code == 200
    assert 'id="kanban-view"' in body
    assert "renderKanban" in body
    assert "function setView" in body


def test_api_templates_lists_sets_and_default(running_server):
    code, body = _get(running_server, "/api/templates")
    assert code == 200
    data = json.loads(body)
    ids = {s["id"] for s in data["sets"]}
    assert ids == {"classic", "modern"}
    assert data["default"] == "classic"


def test_set_default_template_roundtrip(running_server):
    code, data = _post_json(running_server, "/api/settings/default-template", {"set_id": "modern"})
    assert code == 200 and data["default"] == "modern"
    code, body = _get(running_server, "/api/templates")
    assert json.loads(body)["default"] == "modern"


def test_set_default_template_rejects_unknown(running_server):
    code, data = _post_json(running_server, "/api/settings/default-template", {"set_id": "gibtsnicht"})
    assert code == 400


def test_dashboard_contains_template_controls(running_server):
    code, body = _get(running_server, "/")
    assert code == 200
    assert "loadTemplateSets" in body
    assert "/api/settings/default-template" in body
    assert "templateOptions" in body
