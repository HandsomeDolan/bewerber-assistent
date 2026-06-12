import hashlib
from datetime import date
from typing import Optional
from jobspy import scrape_jobs

from bewerber.shared.state_schema import RawJob
from bewerber.discovery.scrapers import scraper_registry


def jobspy_row_to_raw_job_indeed(row: dict) -> RawJob:
    ext = row.get("id")
    url = row.get("job_url") or ""
    if not ext:
        ext = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    posted_raw = row.get("date_posted")
    posted: Optional[date] = None
    if posted_raw:
        try:
            posted = date.fromisoformat(str(posted_raw))
        except ValueError:
            posted = None
    return RawJob(
        board="indeed",
        external_id=str(ext),
        url=url,
        title=row.get("title") or "",
        company=row.get("company") or "",
        location=row.get("location") or "",
        posted_date=posted,
        description=row.get("description") or None,
    )


class IndeedAdapter:
    name = "indeed"

    def search(
        self,
        keywords: list[str],
        locations: list[str],
        max_age_days: int,
    ) -> list[RawJob]:
        results: list[RawJob] = []
        for kw in keywords or [""]:
            for loc in locations or [""]:
                df = scrape_jobs(
                    site_name=["indeed"],
                    search_term=kw,
                    location=loc,
                    hours_old=max_age_days * 24,
                    results_wanted=30,
                    country_indeed="Germany",
                )
                for _, row in df.iterrows():
                    results.append(jobspy_row_to_raw_job_indeed(row))
        return results


scraper_registry["indeed"] = IndeedAdapter()
