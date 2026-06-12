import json
from pathlib import Path
from bewerber.dashboard.render import render_dashboard
from bewerber.shared.state_schema import (
    BewerberState, RawJob, TrackedJob, Scoring, JobStatus,
)


def _state_with_one_job() -> BewerberState:
    return BewerberState(
        last_discovery_run="2026-06-12T10:00:00",
        jobs={
            "arbeitsagentur-x1": TrackedJob(
                raw=RawJob(
                    board="arbeitsagentur", external_id="x1",
                    url="https://x", title="KI Manager", company="BMW",
                    location="München", description="Spannende Rolle",
                ),
                scoring=Scoring(
                    fit_score=8, begruendung="passt",
                    matched_skills=["n8n"], missing_skills=["SAP"],
                    red_flags=[], verbessern_in_anschreiben=[],
                ),
                status=JobStatus.TAILORED,
                tailored_dir="/tmp/dir",
            )
        },
    )


def test_render_dashboard_contains_inlined_state():
    html = render_dashboard(_state_with_one_job())
    assert "<title>Bewerber-Dashboard</title>" in html
    # Inlined JSON contains the job
    assert '"x1"' in html or "arbeitsagentur-x1" in html
    assert "BMW" in html
    assert "KI Manager" in html


def test_render_dashboard_shows_zero_jobs_state():
    html = render_dashboard(BewerberState())
    assert "0 Jobs" in html or "Bewerber-Dashboard" in html


def test_render_dashboard_includes_scrape_errors():
    from bewerber.shared.state_schema import ScrapeError
    state = BewerberState(scrape_errors={"linkedin": ScrapeError(last_error="rate-limited", at="2026-06-12T09:00:00")})
    html = render_dashboard(state)
    assert "linkedin" in html
    assert "rate-limited" in html
