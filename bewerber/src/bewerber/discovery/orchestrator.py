import logging
import re
import threading
from datetime import datetime
from typing import Callable, Optional

from bewerber.shared.llm import LLMClient
from bewerber.shared.state import upsert_job
from bewerber.shared.state_schema import (
    BewerberState, RawJob, Scoring, ScrapeError, TrackedJob,
)
from bewerber.discovery.scrapers import scraper_registry
from bewerber.discovery.searches import SearchEntry, SearchesConfig
from bewerber.discovery.enrich import enrich_job
from bewerber.discovery.scoring import score_job

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _build_exclude_pattern(keywords: list[str]) -> Optional[re.Pattern]:
    """Compile a case-insensitive word-boundary regex matching any keyword.

    Returns None when the list is empty (caller skips filtering).
    """
    cleaned = [kw.strip() for kw in keywords if kw and kw.strip()]
    if not cleaned:
        return None
    pattern = r"\b(?:" + "|".join(re.escape(kw) for kw in cleaned) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


def _apply_excludes(
    raw_jobs: list[RawJob],
    *,
    pattern: Optional[re.Pattern],
    board: str,
    search_name: str,
) -> list[RawJob]:
    """Drop jobs whose title or company matches any exclude keyword.

    Matched before scoring -> saves LLM tokens. Description is intentionally
    not matched: too prone to false positives ("auch ohne SPS-Erfahrung").
    """
    if pattern is None:
        return raw_jobs
    kept: list[RawJob] = []
    dropped = 0
    for raw in raw_jobs:
        haystack = f"{raw.title} {raw.company}"
        if pattern.search(haystack):
            dropped += 1
            continue
        kept.append(raw)
    if dropped:
        log.info(
            "[discover] %s/%s: %d/%d jobs ausgeschlossen via exclude_keywords",
            board, search_name, dropped, len(raw_jobs),
        )
    return kept


def _excludes_for_search(config: SearchesConfig, search: SearchEntry) -> list[str]:
    return list(config.defaults.exclude_keywords) + list(search.exclude_keywords)


def discover(
    config: SearchesConfig,
    *,
    state: BewerberState,
    master_yaml_text: str,
    llm: LLMClient,
    progress: Optional[Callable[[dict], None]] = None,
    checkpoint: Optional[Callable[[BewerberState], None]] = None,
    cancel: Optional[threading.Event] = None,
    per_board_limit: Optional[int] = None,
) -> BewerberState:
    """Run scrape → enrich → score → upsert for each search × board.

    Per-board errors are caught and recorded in state.scrape_errors;
    other boards continue running.

    progress:   nach jedem gescorten Job mit {search, board, done, total} gerufen.
    checkpoint: nach jedem fertigen Board mit dem State gerufen (Zwischenspeichern);
                auch beim Abbruch, damit Teilergebnisse erhalten bleiben.
    cancel:     Event; sobald gesetzt, stoppt der Lauf vor dem naechsten Job/Board.
    per_board_limit: hoechstens N Jobs pro Suche x Board scoren/hinzufuegen
                (wird auch an die Scraper durchgereicht, um Scrape-Zeit zu sparen).
    """
    state.last_discovery_run = _now_iso()

    def _cancelled() -> bool:
        return cancel is not None and cancel.is_set()

    for search in config.searches:
        exclude_pattern = _build_exclude_pattern(_excludes_for_search(config, search))
        for board in search.boards:
            if _cancelled():
                return state
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
                    limit=per_board_limit,
                )
            except Exception as e:  # noqa: BLE001 - isolation is the whole point
                state.scrape_errors[board] = ScrapeError(
                    last_error=str(e),
                    at=_now_iso(),
                )
                continue
            # Clear prior error for this board on success
            state.scrape_errors.pop(board, None)

            raw_jobs = _apply_excludes(
                raw_jobs,
                pattern=exclude_pattern,
                board=board,
                search_name=search.name,
            )

            if per_board_limit:
                raw_jobs = raw_jobs[:per_board_limit]
            total = len(raw_jobs)
            for done, raw in enumerate(raw_jobs, start=1):
                if _cancelled():
                    break
                _process_one(raw, state=state, master_yaml_text=master_yaml_text, llm=llm)
                if progress is not None:
                    progress({
                        "search": search.name, "board": board,
                        "done": done, "total": total,
                    })
            if checkpoint is not None:
                checkpoint(state)
            if _cancelled():
                return state
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
