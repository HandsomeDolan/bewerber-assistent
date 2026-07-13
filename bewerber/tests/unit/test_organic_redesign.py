"""Organic-Redesign: Funktions-Vollstaendigkeit + Design-Tokens pro Seite.

Die ID-/Endpoint-Listen sind das VOR dem Redesign erhobene Inventar der
funktionalen Hooks. Jede Seite muss nach dem Port (a) alle Hooks behalten und
(b) das Organic-Design-System (Token-Marker) enthalten.
"""
import pytest

from bewerber.dashboard.render import (
    render_anlagen_editor,
    render_dashboard,
    render_login,
    render_onboarding,
    render_searches_editor,
)
from bewerber.discovery.searches import SearchesConfig
from bewerber.shared.anlagen import AnlagenConfig
from bewerber.shared.state_schema import BewerberState

ORGANIC_MARKERS = [
    "--color-accent: #c67139",   # Terracotta-Akzent
    "--color-bg: #f5ead8",       # warmer Grund
    "Caprasimo",                 # Heading-Font
]

DASHBOARD_IDS = [
    # Filter + Views
    'id="q"', 'id="filter-status"', 'id="filter-score"', 'id="filter-board"',
    'id="view-table-btn"', 'id="view-kanban-btn"', 'id="view-fokus-btn"',
    'id="kanban-view"', 'id="fokus-view"',
    # Tabelle + Rows (dynamische IDs als Praefix-Marker)
    'id="jobs-table"', 'id="jobs-tbody"', 'id="select-all"',
    'id="start-', 'id="gehalt-', 'id="kontakt-', 'id="sprache-', 'id="set-',
    'id="cvset-', 'id="ansset-', 'id="tailor-btn-', 'id="tailor-status-',
    'id="briefing-btn-', 'id="briefing-status-', 'id="notes-edit-',
    'id="notes-status-', 'id="applied-', 'id="files-',
    # Batch-Tailor + Auswahl
    'id="batch-action-bar"', 'id="batch-selected-count"',
    'id="batch-tailor-params-modal"', 'id="batch-tailor-progress-modal"',
    'id="batch-tailor-start"', 'id="batch-tailor-gehalt"',
    'id="batch-tailor-sprache"', 'id="batch-tailor-set"',
    'id="batch-tailor-rows"', 'id="batch-tailor-summary"',
    'id="batch-tailor-jobcount"', 'id="batch-tailor-close"',
    # Batch-Add
    'id="batch-urls"', 'id="batch-btn"', 'id="batch-modal"',
    'id="batch-rows"', 'id="batch-summary"', 'id="batch-close"',
    # Discover inkl. heutiger Ergaenzungen
    'id="discover-run-btn"', 'id="discover-cancel-btn"', 'id="discover-run-status"',
    # Default-Template + Themes
    'id="default-set"', 'id="default-set-status"',
    'id="theme-file"', 'id="theme-name"', 'id="theme-preview"',
    'id="theme-preview-wrap"', 'id="theme-upload-status"', 'id="my-themes"',
    # Karten-Modal
    'id="card-modal"', 'id="card-modal-body"',
]

DASHBOARD_ENDPOINTS = [
    '/api/batch-add-postings', '/api/batch-tailor', '/api/briefing',
    '/api/delete-job', '/api/discover/run', '/api/discover/cancel',
    '/api/discover/status', '/api/failed-urls/clear', '/api/failed-urls/remove',
    '/api/job-files', '/api/mark', '/api/notes-set',
    '/api/settings/default-template', '/api/tailor', '/api/templates',
    '/api/themes', '/logout',
]

LOGIN_IDS = [
    'id="login-form"', 'id="login-username"', 'id="login-passwort"', 'id="login-btn"',
    'id="register-form"', 'id="reg-vorname"', 'id="reg-nachname"',
    'id="reg-passwort"', 'id="reg-invite"', 'id="reg-btn"',
    'id="error"', 'id="success"', 'id="subtitle"',
]

ONBOARDING_IDS = [
    'id="step-1"', 'id="step-2"', 'id="step-3"', 'id="step-4"',
    'id="dropzone"', 'id="dropzone-text"', 'id="file-input"', 'id="file-list"',
    'id="extract-btn"', 'id="phase-text"', 'id="status-box"',
    'id="onb-keywords"', 'id="onb-locations"', 'id="onb-exclude"',
    'id="onb-max-days"', 'id="onb-anlagen-path"', 'id="onb-anlagen-result"',
    'id="onb-style-checkboxes"', 'id="finish-btn"', 'id="finish-status"',
    'id="finish-status-box"',
]

SEARCHES_IDS = [
    'id="defaults-section"', 'id="searches-section"', 'id="searches-list"',
    'id="search-card-template"', 'id="add-btn"', 'id="reload-btn"',
    'id="save-btn"', 'id="dirty"', 'id="status"', 'id="initial-config"',
    'id="kw-modal"', 'id="kw-mode-generate"', 'id="kw-mode-manual"',
    'id="kw-desc"', 'id="kw-manual"', 'id="kw-suggestions"', 'id="kw-generate"',
    'id="kw-apply"', 'id="kw-cancel"', 'id="kw-status"', 'id="kw-linkedin-hint"',
]

ANLAGEN_IDS = [
    'id="anlagen-list"', 'id="anlage-card-template"', 'id="add-btn"',
    'id="reload-btn"', 'id="save-btn"', 'id="dirty"', 'id="status"',
    'id="initial-config"', 'id="anlagen-upload"', 'id="anlagen-upload-status"',
]


def _assert_all(html: str, needles: list[str], page: str) -> None:
    missing = [n for n in needles if n not in html]
    assert not missing, f"{page}: fehlende Marker: {missing}"


@pytest.fixture
def pages():
    return {
        "dashboard": render_dashboard(BewerberState()),
        "login": render_login(),
        "onboarding": render_onboarding(current_user="test"),
        "searches": render_searches_editor(SearchesConfig()),
        "anlagen": render_anlagen_editor(AnlagenConfig()),
    }


def test_all_pages_use_organic_design_system(pages):
    for name, html in pages.items():
        _assert_all(html, ORGANIC_MARKERS, name)


def test_dashboard_keeps_all_functional_ids(pages):
    _assert_all(pages["dashboard"], DASHBOARD_IDS, "dashboard")


def test_dashboard_keeps_all_endpoints(pages):
    _assert_all(pages["dashboard"], DASHBOARD_ENDPOINTS, "dashboard")


def test_login_keeps_all_functional_ids(pages):
    _assert_all(pages["login"], LOGIN_IDS, "login")
    for ep in ["/login", "/api/register"]:
        assert ep in pages["login"]


def test_onboarding_keeps_all_functional_ids(pages):
    _assert_all(pages["onboarding"], ONBOARDING_IDS, "onboarding")
    for ep in ["/api/onboarding/extract", "/api/onboarding/save",
               "/api/onboarding/scan-folder", "/api/onboarding/status"]:
        assert ep in pages["onboarding"]


def test_searches_keeps_all_functional_ids(pages):
    _assert_all(pages["searches"], SEARCHES_IDS, "searches")
    for ep in ["/api/searches", "/api/keywords/generate"]:
        assert ep in pages["searches"]
    # Heutige Verbesserung bleibt: neue Card oben + Highlight
    assert "search-card--new" in pages["searches"]
    assert "list.prepend(" in pages["searches"]


def test_anlagen_keeps_all_functional_ids(pages):
    _assert_all(pages["anlagen"], ANLAGEN_IDS, "anlagen")
    for ep in ["/api/anlagen", "/api/anlagen/verify", "/api/anlagen/upload"]:
        assert ep in pages["anlagen"]


def test_dashboard_has_no_single_add_mode():
    """Design-Konflikt aufgeloest: Add-Dialog ist batch-only (Einzel-Add wurde
    heute entfernt) - keine Firma/Rolle-Eingabefelder im Add-Flow."""
    html = render_dashboard(BewerberState())
    assert "addPostingFromUrl" not in html
    assert "/api/add-posting" not in html.replace("/api/batch-add-postings", "")
