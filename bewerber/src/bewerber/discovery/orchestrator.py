from datetime import datetime
from typing import Optional

from bewerber.shared.llm import LLMClient
from bewerber.shared.state import upsert_job
from bewerber.shared.state_schema import (
    BewerberState, RawJob, Scoring, ScrapeError, TrackedJob,
)
from bewerber.discovery.scrapers import scraper_registry
from bewerber.discovery.searches import SearchesConfig
from bewerber.discovery.enrich import enrich_job
from bewerber.discovery.scoring import score_job


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def discover(
    config: SearchesConfig,
    *,
    state: BewerberState,
    master_yaml_text: str,
    llm: LLMClient,
) -> BewerberState:
    """Run scrape → enrich → score → upsert for each search × board.

    Per-board errors are caught and recorded in state.scrape_errors;
    other boards continue running.
    """
    state.last_discovery_run = _now_iso()

    for search in config.searches:
        for board in search.boards:
            adapter = scraper_registry.get(board)
            if adapter is None:
                state.scrape_errors[board] = ScrapeError(
                    last_error=f"No adapter registered for board {board!r}",
                    at=_now_iso(),
                )
                continue
            try:
                raw_jobs = adapter.search(
                    keywords=search.keywords,
                    locations=config.defaults.locations,
                    max_age_days=config.defaults.date_posted_max_days,
                )
            except Exception as e:  # noqa: BLE001 - isolation is the whole point
                state.scrape_errors[board] = ScrapeError(
                    last_error=str(e),
                    at=_now_iso(),
                )
                continue
            # Clear prior error for this board on success
            state.scrape_errors.pop(board, None)

            for raw in raw_jobs:
                _process_one(raw, state=state, master_yaml_text=master_yaml_text, llm=llm)
    return state


def _process_one(
    raw: RawJob,
    *,
    state: BewerberState,
    master_yaml_text: str,
    llm: LLMClient,
) -> None:
    enriched = enrich_job(raw)
    job_id = f"{enriched.board}-{enriched.external_id}"
    existing = state.jobs.get(job_id)

    if (
        existing is not None
        and existing.scoring is not None
        and enriched.description_hash is not None
        and enriched.description_hash == existing.raw.description_hash
    ):
        # No content change → keep existing scoring; just upsert (raw may have fresher fields)
        tracked = TrackedJob(raw=enriched, scoring=existing.scoring)
    else:
        scoring = score_job(job=enriched, master_yaml_text=master_yaml_text, llm=llm)
        tracked = TrackedJob(
            raw=enriched,
            scoring=scoring,
            first_seen=_now_iso() if existing is None else existing.first_seen,
        )

    upsert_job(state, tracked)
