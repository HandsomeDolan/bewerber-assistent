import hashlib
from datetime import date
from typing import Optional
import pandas as pd
from jobspy import scrape_jobs

from bewerber.shared.state_schema import RawJob
from bewerber.discovery.scrapers import scraper_registry


def _clean(v) -> str:
    """Convert pandas NaN / None / non-string values to empty string.

    Uses pandas.isna() to catch np.nan, pd.NA, math.nan, None, NaT consistently.
    """
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v)


def jobspy_row_to_raw_job(row: dict) -> RawJob:
    """Map a single jobspy DataFrame row (LinkedIn) to RawJob."""
    ext = _clean(row.get("id"))
    url = _clean(row.get("job_url"))
    if not ext:
        ext = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    posted_clean = _clean(row.get("date_posted"))
    posted: Optional[date] = None
    if posted_clean:
        try:
            posted = date.fromisoformat(posted_clean)
        except ValueError:
            posted = None
    desc = _clean(row.get("description"))
    return RawJob(
        board="linkedin",
        external_id=ext,
        url=url,
        title=_clean(row.get("title")),
        company=_clean(row.get("company")),
        location=_clean(row.get("location")),
        posted_date=posted,
        description=desc or None,
    )


class LinkedInAdapter:
    name = "linkedin"

    def search(
        self,
        keywords: list[str],
        locations: list[str],
        max_age_days: int,
        limit: int | None = None,
    ) -> list[RawJob]:
        results: list[RawJob] = []
        for kw in keywords or [""]:
            for loc in locations or [""]:
                # limit gilt pro Quelle GESAMT: nur noch den Rest anfordern,
                # weitere Keyword/Ort-Kombis ueberspringen, sobald voll.
                remaining = (limit - len(results)) if limit else 30
                if remaining <= 0:
                    return results
                df = scrape_jobs(
                    site_name=["linkedin"],
                    search_term=kw,
                    location=loc,
                    hours_old=max_age_days * 24,
                    results_wanted=remaining,
                    country_indeed="Germany",
                )
                for _, row in df.iterrows():
                    if limit and len(results) >= limit:
                        return results
                    results.append(jobspy_row_to_raw_job(row))
        return results


scraper_registry["linkedin"] = LinkedInAdapter()
