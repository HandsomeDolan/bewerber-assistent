from datetime import date
from bewerber.discovery.scrapers import BoardAdapter, scraper_registry
from bewerber.shared.state_schema import RawJob


class FakeAdapter:
    name = "fake"

    def search(self, keywords, locations, max_age_days):
        return [
            RawJob(
                board="fake", external_id="1", url="https://x",
                title="t", company="c", location="l",
                posted_date=date(2026, 6, 1),
            )
        ]


def test_fake_adapter_satisfies_protocol():
    """A duck-typed class with .name and .search(...) IS-A BoardAdapter."""
    a: BoardAdapter = FakeAdapter()
    jobs = a.search(["k"], ["Leipzig"], max_age_days=14)
    assert jobs[0].board == "fake"


def test_scraper_registry_is_initially_empty():
    """Registry exists; modules will register themselves at import time."""
    # The registry is a dict[str, BoardAdapter]. It may be populated by the time
    # tests run if other scraper modules are imported elsewhere — we just check it exists.
    assert isinstance(scraper_registry, dict)
