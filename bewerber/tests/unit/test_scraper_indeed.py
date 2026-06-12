from bewerber.discovery.scrapers.indeed import IndeedAdapter, jobspy_row_to_raw_job_indeed


def _fake_dataframe(rows):
    class _DF:
        def iterrows(self):
            return iter([(i, r) for i, r in enumerate(rows)])
        def __len__(self):
            return len(rows)
    return _DF()


def test_jobspy_row_to_raw_job_indeed_sets_board():
    row = {
        "site": "indeed", "id": "id-42", "job_url": "https://de.indeed.com/job/42",
        "title": "t", "company": "c", "location": "l",
        "date_posted": None, "description": None,
    }
    job = jobspy_row_to_raw_job_indeed(row)
    assert job.board == "indeed"
    assert job.external_id == "id-42"


def test_adapter_calls_jobspy_with_indeed_only(mocker):
    rows = [{
        "site": "indeed", "id": "1", "job_url": "https://x", "title": "t",
        "company": "c", "location": "l", "date_posted": None, "description": None,
    }]
    fake = mocker.patch(
        "bewerber.discovery.scrapers.indeed.scrape_jobs",
        return_value=_fake_dataframe(rows),
    )
    adapter = IndeedAdapter()
    jobs = adapter.search(keywords=["KI Manager"], locations=["Leipzig"], max_age_days=14)
    assert len(jobs) == 1
    kwargs = fake.call_args.kwargs
    assert kwargs["site_name"] == ["indeed"]
    assert kwargs["country_indeed"] == "Germany"


def test_adapter_registers_in_scraper_registry():
    from bewerber.discovery.scrapers import scraper_registry
    from bewerber.discovery.scrapers.indeed import IndeedAdapter  # noqa
    assert "indeed" in scraper_registry
    assert isinstance(scraper_registry["indeed"], IndeedAdapter)
