from datetime import date
from bewerber.discovery.scrapers.linkedin import (
    LinkedInAdapter, jobspy_row_to_raw_job,
)


def _fake_dataframe(rows):
    """Build a mock pandas-like object yielding `rows` from .iterrows()."""
    class _DF:
        def iterrows(self):
            return iter([(i, r) for i, r in enumerate(rows)])
        def __len__(self):
            return len(rows)
    return _DF()


def test_jobspy_row_to_raw_job():
    row = {
        "site": "linkedin",
        "id": "li-12345",
        "job_url": "https://www.linkedin.com/jobs/view/12345",
        "title": "AI Product Manager",
        "company": "Acme",
        "location": "Berlin",
        "date_posted": "2026-06-05",
        "description": "Spannende Rolle ...",
    }
    job = jobspy_row_to_raw_job(row)
    assert job.board == "linkedin"
    assert job.external_id == "li-12345"
    assert job.url.endswith("/12345")
    assert job.title == "AI Product Manager"
    assert job.posted_date == date(2026, 6, 5)
    assert job.description.startswith("Spannende")


def test_jobspy_row_missing_id_falls_back_to_url_hash():
    row = {
        "site": "linkedin",
        "job_url": "https://linkedin.com/jobs/view/99999",
        "title": "x", "company": "c", "location": "l", "id": None,
        "date_posted": None, "description": None,
    }
    job = jobspy_row_to_raw_job(row)
    assert job.external_id  # non-empty derived from URL


def test_adapter_calls_jobspy_with_linkedin_only(mocker):
    rows = [{
        "site": "linkedin", "id": "1", "job_url": "https://x", "title": "t",
        "company": "c", "location": "l", "date_posted": None, "description": None,
    }]
    fake_scrape = mocker.patch(
        "bewerber.discovery.scrapers.linkedin.scrape_jobs",
        return_value=_fake_dataframe(rows),
    )
    adapter = LinkedInAdapter()
    jobs = adapter.search(keywords=["KI Manager"], locations=["Leipzig"], max_age_days=14)
    assert len(jobs) == 1
    args, kwargs = fake_scrape.call_args
    assert kwargs["site_name"] == ["linkedin"]
    assert kwargs["search_term"] == "KI Manager"
    assert kwargs["location"] == "Leipzig"
    assert kwargs["hours_old"] == 14 * 24  # max_age_days → hours


def test_adapter_registers_in_scraper_registry():
    from bewerber.discovery.scrapers import scraper_registry
    from bewerber.discovery.scrapers.linkedin import LinkedInAdapter  # noqa: F401  triggers registration
    assert "linkedin" in scraper_registry
    assert isinstance(scraper_registry["linkedin"], LinkedInAdapter)
