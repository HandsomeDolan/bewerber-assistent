import hashlib
from pathlib import Path
from bewerber.discovery.enrich import (
    enrich_job, extract_main_text, _hash_description,
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
