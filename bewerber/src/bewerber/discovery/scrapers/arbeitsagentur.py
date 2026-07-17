import os
from datetime import date, timedelta
from typing import Optional
import requests

from bewerber.shared.state_schema import RawJob
from bewerber.discovery.scrapers import scraper_registry


API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
DETAIL_URL_BASE = "https://www.arbeitsagentur.de/jobsuche/jobdetail"


def build_detail_url(refnr: str) -> str:
    return f"{DETAIL_URL_BASE}/{refnr}"


def parse_arbeitsagentur_response(data: dict) -> list[RawJob]:
    """Map the Arbeitsagentur v4 JSON response to RawJob list."""
    result: list[RawJob] = []
    for entry in data.get("stellenangebote", []):
        refnr = entry.get("refnr")
        if not refnr:
            continue
        ort = (entry.get("arbeitsort") or {}).get("ort") or ""
        published = entry.get("aktuelleVeroeffentlichungsdatum")
        posted: Optional[date] = None
        if published:
            try:
                posted = date.fromisoformat(published)
            except ValueError:
                posted = None
        result.append(RawJob(
            board="arbeitsagentur",
            external_id=refnr,
            url=build_detail_url(refnr),
            title=entry.get("titel") or entry.get("beruf") or "",
            company=entry.get("arbeitgeber") or "",
            location=ort,
            posted_date=posted,
        ))
    return result


class ArbeitsagenturAdapter:
    name = "arbeitsagentur"

    def __init__(self, api_key: Optional[str] = None) -> None:
        # Explicit override only; otherwise read from env lazily in search()
        # so that load_dotenv() in cli.py runs first.
        self._explicit_api_key = api_key

    @property
    def api_key(self) -> str:
        if self._explicit_api_key:
            return self._explicit_api_key
        return os.environ.get("ARBEITSAGENTUR_API_KEY", "")

    def search(
        self,
        keywords: list[str],
        locations: list[str],
        max_age_days: int,
        limit: int | None = None,
    ) -> list[RawJob]:
        key = self.api_key
        if not key:
            raise RuntimeError(
                "ARBEITSAGENTUR_API_KEY not set. "
                "Register at https://jobsuche.api.bund.dev and put the key in .env."
            )
        # Combine keywords with OR; multiple location lookups happen by repeating the request per location.
        was = " OR ".join(keywords) if keywords else ""
        results: list[RawJob] = []
        cutoff = date.today() - timedelta(days=max_age_days)
        for loc in locations or [""]:
            if limit and len(results) >= limit:
                break
            size = min(50, limit - len(results)) if limit else 50
            params = {"was": was, "wo": loc, "size": size, "angebotsart": 1}
            resp = requests.get(
                url=API_BASE,
                headers={"X-API-Key": key, "User-Agent": "bewerber/0.1"},
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            for job in parse_arbeitsagentur_response(resp.json()):
                if job.posted_date and job.posted_date < cutoff:
                    continue
                if limit and len(results) >= limit:
                    break
                results.append(job)
        return results


# Register a default instance (api_key picked up from env at first use).
scraper_registry["arbeitsagentur"] = ArbeitsagenturAdapter()
