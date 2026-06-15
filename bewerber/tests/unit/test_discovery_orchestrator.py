from datetime import date
from bewerber.discovery.orchestrator import discover
from bewerber.discovery.searches import SearchesConfig, SearchEntry, SearchDefaults
from bewerber.shared.state_schema import (
    BewerberState, RawJob, Scoring, JobStatus,
)


def _job(board="arbeitsagentur", ext="1", desc="Beschreibung") -> RawJob:
    return RawJob(
        board=board, external_id=ext,
        url=f"https://{board}/{ext}",
        title="KI Manager", company="Acme", location="Leipzig",
        description=desc,
    )


def test_discover_runs_each_board_per_search_and_upserts(tmp_path, mocker, monkeypatch):
    """Two searches × two boards → 4 scraper calls; each result scored and stored."""
    fake_adapter_a = mocker.Mock()
    fake_adapter_a.name = "arbeitsagentur"
    fake_adapter_a.search.return_value = [_job("arbeitsagentur", "1")]
    fake_adapter_b = mocker.Mock()
    fake_adapter_b.name = "linkedin"
    fake_adapter_b.search.return_value = [_job("linkedin", "li-2")]

    fake_registry = {"arbeitsagentur": fake_adapter_a, "linkedin": fake_adapter_b}
    monkeypatch.setattr("bewerber.discovery.orchestrator.scraper_registry", fake_registry)

    fake_enrich = mocker.patch(
        "bewerber.discovery.orchestrator.enrich_job",
        side_effect=lambda j: j,
    )
    fake_score = mocker.patch(
        "bewerber.discovery.orchestrator.score_job",
        return_value=Scoring(
            fit_score=7, begruendung="ok", matched_skills=[],
            missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
        ),
    )

    config = SearchesConfig(
        defaults=SearchDefaults(locations=["Leipzig"], date_posted_max_days=14),
        searches=[
            SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur", "linkedin"]),
            SearchEntry(name="B", keywords=["Manager"], boards=["arbeitsagentur"]),
        ],
    )

    state = BewerberState()
    fake_llm = mocker.Mock()
    discover(config, state=state, master_yaml_text="master", llm=fake_llm)

    # 3 scraper invocations: search-A × 2 boards + search-B × 1 board
    assert fake_adapter_a.search.call_count + fake_adapter_b.search.call_count == 3
    # Enrich + score called for each unique RawJob
    assert fake_enrich.call_count == 3
    assert fake_score.call_count == 3
    # Both jobs in state
    assert "arbeitsagentur-1" in state.jobs
    assert "linkedin-li-2" in state.jobs
    # Scoring attached
    assert state.jobs["arbeitsagentur-1"].scoring.fit_score == 7


def test_discover_isolates_board_failures(tmp_path, mocker, monkeypatch):
    """If one scraper raises, others still run, and an error is recorded in state."""
    ok = mocker.Mock()
    ok.name = "arbeitsagentur"
    ok.search.return_value = [_job("arbeitsagentur", "1")]
    broken = mocker.Mock()
    broken.name = "linkedin"
    broken.search.side_effect = RuntimeError("rate-limited")

    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": ok, "linkedin": broken},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=7, begruendung="x", matched_skills=[], missing_skills=[],
        red_flags=[], verbessern_in_anschreiben=[],
    ))

    config = SearchesConfig(searches=[
        SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur", "linkedin"]),
    ])
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    assert "arbeitsagentur-1" in state.jobs  # ok scraper succeeded
    assert "linkedin" in state.scrape_errors
    assert "rate-limited" in state.scrape_errors["linkedin"].last_error


def test_discover_keeps_jobs_no_longer_in_listing(mocker, monkeypatch):
    """Jobs already in state must persist across discovery runs even if the
    scraper no longer returns them (posting expired on Arbeitsagentur).
    The user's status / notes / tailored_dir must be preserved."""
    from bewerber.shared.state_schema import TrackedJob
    state = BewerberState()
    old_job = TrackedJob(
        raw=_job("arbeitsagentur", "expired-1", desc="old"),
        scoring=Scoring(fit_score=8, begruendung="x", matched_skills=[],
                       missing_skills=[], red_flags=[], verbessern_in_anschreiben=[]),
        status=JobStatus.APPLIED,
        application_link="https://applied.example",
        notes="Recruiter angerufen",
        tailored_dir="/some/path",
    )
    state.jobs["arbeitsagentur-expired-1"] = old_job

    # New scrape returns a DIFFERENT job; the expired one is absent
    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [_job("arbeitsagentur", "new-2")]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=6, begruendung="x", matched_skills=[],
        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
    ))

    config = SearchesConfig(searches=[
        SearchEntry(name="X", keywords=["KI"], boards=["arbeitsagentur"]),
    ])
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    # Old job is still there with status + curated fields intact
    assert "arbeitsagentur-expired-1" in state.jobs
    kept = state.jobs["arbeitsagentur-expired-1"]
    assert kept.status == JobStatus.APPLIED
    assert kept.notes == "Recruiter angerufen"
    assert kept.application_link == "https://applied.example"
    assert kept.tailored_dir == "/some/path"
    # New job also stored
    assert "arbeitsagentur-new-2" in state.jobs


def test_discover_skips_rescoring_when_description_hash_unchanged(mocker, monkeypatch):
    """If a job comes back from scrape with same description_hash, do not re-score."""
    pre_existing = _job("arbeitsagentur", "1", desc="A")
    pre_existing = pre_existing.model_copy(update={"description_hash": "h-A"})
    state = BewerberState()
    from bewerber.shared.state_schema import TrackedJob
    state.jobs["arbeitsagentur-1"] = TrackedJob(
        raw=pre_existing,
        scoring=Scoring(
            fit_score=9, begruendung="alt", matched_skills=[],
            missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
        ),
        status=JobStatus.APPLIED,
    )

    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [pre_existing]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    rescore = mocker.patch("bewerber.discovery.orchestrator.score_job")

    config = SearchesConfig(searches=[
        SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur"]),
    ])
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    rescore.assert_not_called()  # description unchanged → no re-scoring
    # Existing scoring + status preserved
    assert state.jobs["arbeitsagentur-1"].scoring.fit_score == 9
    assert state.jobs["arbeitsagentur-1"].status == JobStatus.APPLIED
