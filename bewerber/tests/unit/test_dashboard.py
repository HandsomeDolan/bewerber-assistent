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


def test_render_dashboard_has_discover_cancel_button_and_endpoint():
    """Laufende Discover-Runs muessen aus der UI abbrechbar sein."""
    html = render_dashboard(BewerberState())
    assert 'id="discover-cancel-btn"' in html
    assert "/api/discover/cancel" in html


def test_render_searches_editor_prepends_and_highlights_new_card():
    """'+ Suche hinzufuegen' fuegt die neue Card VOR der ersten ein (prepend)
    und hebt sie dezent hervor, damit sie wahrgenommen wird."""
    from bewerber.dashboard.render import render_searches_editor
    from bewerber.discovery.searches import SearchesConfig
    html = render_searches_editor(SearchesConfig())
    assert "search-card--new" in html          # Highlight-Klasse (CSS + JS)
    assert "list.prepend(" in html             # neue Card kommt nach oben
    assert "list.appendChild(buildSearchCard({" not in html  # alter Append-Weg raus


def test_render_dashboard_has_no_single_add_posting_but_keeps_batch():
    """Einzel-URL-Hinzufuegen wurde entfernt - Batch deckt den Fall ab."""
    html = render_dashboard(BewerberState())
    assert "manuell hinzufuegen" not in html
    assert "addPostingFromUrl" not in html
    assert "Mehrere URLs auf einmal verarbeiten" in html


def test_render_dashboard_user_menu_with_account_delete():
    """Klick auf den Namen -> Menue mit Logout + Account-Loeschung (mit Warn-Dialog)."""
    html = render_dashboard(BewerberState(), current_user="Max Muster")
    assert 'id="user-menu-btn"' in html
    assert 'id="user-menu"' in html
    assert 'id="account-delete-modal"' in html
    assert "/api/account/delete" in html
    # Warnung benennt explizit, was verloren geht
    assert "Dokumente" in html and "Suchen" in html
    assert "nicht rückgängig" in html


def test_render_dashboard_matches_organic_soll_layout():
    """Abgleich mit dem Soll-Mockup: Nav-Bar, 'Bewerbungen'-Titel, Status-Zaehlung
    in der Meta-Zeile, Add-Dialog statt Details-Box, Score-Badges, Datei-Button."""
    from bewerber.shared.state_schema import RawJob, TrackedJob
    state = BewerberState(jobs={
        "a-1": TrackedJob(raw=RawJob(board="manual", external_id="1", url="https://x/1",
                                     title="T1", company="C1", location="L"), status="applied"),
        "a-2": TrackedJob(raw=RawJob(board="manual", external_id="2", url="https://x/2",
                                     title="T2", company="C2", location="L"), status="interview"),
    })
    html = render_dashboard(state, current_user="steve")
    assert '<nav class="nav"' in html
    assert ">Bewerbungen</h1>" in html
    assert "1 beworben" in html and "1 eingeladen" in html
    assert 'id="add-dialog"' in html
    assert 'id="theme-file-label"' in html
    assert "score-badge" in html
    assert 'id="view-fokus-btn"' in html  # Switcher bleibt komplett
    # Detail-Ansicht nach Soll: Kicker, Skill-Pills (matched gruen/missing rot), Flag-Zeilen
    assert "detail-kicker" in html
    assert "tag-missing" in html
    assert "red-flag" in html


def test_render_dashboard_has_discover_limit_dialog():
    """Discover starten oeffnet einen Dialog mit Job-Limit (5/15/30/60,
    Default 15) und Zeitschaetzung pro Option."""
    html = render_dashboard(BewerberState(), current_user="steve")
    assert 'id="discover-dialog"' in html
    for v in (5, 15, 30, 60):
        assert f'value="{v}"' in html
    assert 'id="discover-limit-15"' in html and "checked" in html
    assert "discover-est-" in html  # Zeitschaetzungs-Spans
    assert "openDiscoverDialog" in html
