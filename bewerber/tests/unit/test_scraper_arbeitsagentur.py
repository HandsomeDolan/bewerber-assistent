import json
from pathlib import Path
from datetime import date
from bewerber.discovery.scrapers.arbeitsagentur import (
    ArbeitsagenturAdapter, parse_arbeitsagentur_response, build_detail_url,
)


def test_parse_response_extracts_raw_jobs(fixtures_dir: Path):
    data = json.loads((fixtures_dir / "arbeitsagentur_response.json").read_text())
    jobs = parse_arbeitsagentur_response(data)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.board == "arbeitsagentur"
    assert j.external_id == "10001-1003091744-S"
    assert "Business AI Consultant" in j.title
    assert j.company == "2b AHEAD ThinkTank GmbH"
    assert j.location == "Leipzig"
    assert j.posted_date == date(2026, 5, 19)
    assert j.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003091744-S"


def test_build_detail_url():
    assert build_detail_url("10001-1003091744-S") == (
        "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003091744-S"
    )


def test_adapter_calls_api_and_parses(mocker, fixtures_dir: Path):
    fixture_data = json.loads((fixtures_dir / "arbeitsagentur_response.json").read_text())
    fake_resp = mocker.Mock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = fixture_data
    fake_resp.raise_for_status = mocker.Mock()
    mocker.patch(
        "bewerber.discovery.scrapers.arbeitsagentur.requests.get",
        return_value=fake_resp,
    )

    adapter = ArbeitsagenturAdapter(api_key="test-key")
    jobs = adapter.search(keywords=["KI Manager"], locations=["Leipzig"], max_age_days=30)
    assert len(jobs) == 2

    import bewerber.discovery.scrapers.arbeitsagentur as mod
    args, kwargs = mod.requests.get.call_args
    assert "X-API-Key" in kwargs["headers"]
    assert kwargs["headers"]["X-API-Key"] == "test-key"
    assert "was=KI" in kwargs["url"] or kwargs["params"]["was"] == "KI Manager"


def test_adapter_registers_in_scraper_registry():
    from bewerber.discovery.scrapers import scraper_registry
    from bewerber.discovery.scrapers.arbeitsagentur import ArbeitsagenturAdapter  # import triggers registration
    assert "arbeitsagentur" in scraper_registry
    assert isinstance(scraper_registry["arbeitsagentur"], ArbeitsagenturAdapter)
