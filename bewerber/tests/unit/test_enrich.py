import hashlib
from pathlib import Path
from bewerber.discovery.enrich import (
    enrich_job, extract_main_text, _hash_description, extract_arbeitsmodell,
)
from bewerber.shared.state_schema import RawJob


def _raw(description=None) -> RawJob:
    return RawJob(
        board="arbeitsagentur",
        external_id="x1",
        url="https://example.com/job/1",
        title="t", company="c", location="l",
        description=description,
    )


def test_extract_main_text_finds_main_content(fixtures_dir: Path):
    html = (fixtures_dir / "posting_with_full_description.html").read_text(encoding="utf-8")
    text = extract_main_text(html)
    assert "Business AI Consultant" in text
    assert "n8n" in text
    assert "footer noise" not in text  # readability strips boilerplate


def test_enrich_keeps_existing_description(mocker):
    job = _raw(description="bereits da")
    fake_get = mocker.patch("bewerber.discovery.enrich.requests.get")
    result = enrich_job(job)
    assert result.description == "bereits da"
    fake_get.assert_not_called()


def test_enrich_fetches_and_sets_description_when_missing(mocker, fixtures_dir: Path):
    html = (fixtures_dir / "posting_with_full_description.html").read_text(encoding="utf-8")
    fake_resp = mocker.Mock()
    fake_resp.text = html
    fake_resp.raise_for_status = mocker.Mock()
    fake_resp.status_code = 200
    mocker.patch("bewerber.discovery.enrich.requests.get", return_value=fake_resp)

    job = _raw(description=None)
    result = enrich_job(job)
    assert "Business AI Consultant" in (result.description or "")
    assert result.description_hash is not None
    assert result.description_hash == _hash_description(result.description)


def test_enrich_swallows_http_failure_and_returns_job_unchanged(mocker):
    job = _raw(description=None)
    mocker.patch(
        "bewerber.discovery.enrich.requests.get",
        side_effect=__import__("requests").RequestException("network"),
    )
    result = enrich_job(job)
    assert result.description is None  # not raised, just left empty


# --- arbeitsmodell extractor ---

def test_arbeitsmodell_none_when_no_text():
    assert extract_arbeitsmodell(None) is None
    assert extract_arbeitsmodell("") is None


def test_arbeitsmodell_none_when_no_keywords():
    assert extract_arbeitsmodell("KI Manager bei Acme in Leipzig, Vollzeit, 5 Tage pro Woche im Buero.") is None


def test_arbeitsmodell_remote_explicit_full():
    for s in [
        "Diese Stelle ist 100% remote.",
        "Wir bieten fully remote work weltweit.",
        "Vollstaendig remote moeglich von Tag 1.",
        "Remote-first Setup.",
        "Remote-only Stelle.",
    ]:
        assert extract_arbeitsmodell(s) == "remote", f"failed for {s!r}"


def test_arbeitsmodell_hybrid_explicit():
    for s in [
        "Hybrides Arbeitsmodell mit 2 Tagen Home Office.",
        "Homeoffice möglich nach Probezeit.",
        "Remote möglich bis zu 60% der Zeit.",
        "Mobiles Arbeiten moeglich.",
        "Teilweise remote.",
    ]:
        assert extract_arbeitsmodell(s) == "hybrid", f"failed for {s!r}"


def test_arbeitsmodell_ambiguous_remote_falls_back_to_hybrid():
    """Wenn 'remote' ohne 100%-Qualifier auftaucht, lieber konservativ als hybrid."""
    assert extract_arbeitsmodell("Wir bieten Remote-Optionen und Flexibilitaet.") == "hybrid"
    assert extract_arbeitsmodell("Home Office vorhanden.") == "hybrid"


def test_arbeitsmodell_case_insensitive():
    assert extract_arbeitsmodell("HYBRID work model") == "hybrid"
    assert extract_arbeitsmodell("100% REMOTE") == "remote"


def test_enrich_fills_arbeitsmodell_when_description_already_present():
    job = _raw(description="Stelle mit hybridem Arbeitsmodell.")
    result = enrich_job(job)
    assert result.arbeitsmodell == "hybrid"


def test_enrich_does_not_overwrite_existing_arbeitsmodell():
    job = RawJob(
        board="x", external_id="1", url="u", title="t", company="c", location="l",
        description="Hybrides Modell.", arbeitsmodell="remote",  # vorher manuell gesetzt
    )
    result = enrich_job(job)
    assert result.arbeitsmodell == "remote"  # bleibt
