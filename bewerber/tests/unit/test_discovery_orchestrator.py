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


def test_global_exclude_keywords_filter_matching_titles(mocker, monkeypatch):
    """defaults.exclude_keywords=['SPS'] -> SPS-titled jobs dropped before scoring."""
    sps_job = _job("arbeitsagentur", "1")
    sps_job = sps_job.model_copy(update={"title": "SPS-Programmierer (m/w/d)"})
    ai_job = _job("arbeitsagentur", "2")
    ai_job = ai_job.model_copy(update={"title": "KI Manager"})

    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [sps_job, ai_job]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    score = mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=7, begruendung="ok", matched_skills=[], missing_skills=[],
        red_flags=[], verbessern_in_anschreiben=[],
    ))

    config = SearchesConfig(
        defaults=SearchDefaults(locations=["Leipzig"], exclude_keywords=["SPS"]),
        searches=[SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur"])],
    )
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    assert "arbeitsagentur-1" not in state.jobs  # SPS dropped
    assert "arbeitsagentur-2" in state.jobs
    assert score.call_count == 1  # only the KI job got scored (LLM-tokens saved)


def test_per_search_excludes_combine_with_global(mocker, monkeypatch):
    """Per-search exclude_keywords vereinigt sich mit globaler Liste."""
    sps_job = _job("arbeitsagentur", "1").model_copy(update={"title": "SPS Engineer"})
    vertrieb_job = _job("arbeitsagentur", "2").model_copy(update={"title": "Vertrieb KI"})
    keep_job = _job("arbeitsagentur", "3").model_copy(update={"title": "KI Consultant"})

    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [sps_job, vertrieb_job, keep_job]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=7, begruendung="x", matched_skills=[], missing_skills=[],
        red_flags=[], verbessern_in_anschreiben=[],
    ))

    config = SearchesConfig(
        defaults=SearchDefaults(exclude_keywords=["SPS"]),
        searches=[SearchEntry(
            name="A", keywords=["KI"], boards=["arbeitsagentur"],
            exclude_keywords=["Vertrieb"],
        )],
    )
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    assert set(state.jobs.keys()) == {"arbeitsagentur-3"}


def test_exclude_keywords_case_insensitive(mocker, monkeypatch):
    """'sps' lowercase im Filter matched 'SPS' im Titel."""
    j = _job("arbeitsagentur", "1").model_copy(update={"title": "SPS-Techniker"})
    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [j]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job")

    config = SearchesConfig(
        defaults=SearchDefaults(exclude_keywords=["sps"]),
        searches=[SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur"])],
    )
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    assert state.jobs == {}


def test_exclude_keywords_word_boundary_no_substring_false_positive(mocker, monkeypatch):
    """Filter 'PLS' darf NICHT 'PLSQL Developer' droppen (Wortgrenze)."""
    plsql = _job("arbeitsagentur", "1").model_copy(update={"title": "PLSQL Developer (m/w/d)"})
    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [plsql]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=7, begruendung="x", matched_skills=[], missing_skills=[],
        red_flags=[], verbessern_in_anschreiben=[],
    ))

    config = SearchesConfig(
        defaults=SearchDefaults(exclude_keywords=["PLS"]),
        searches=[SearchEntry(name="A", keywords=["x"], boards=["arbeitsagentur"])],
    )
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    # PLSQL bleibt drin - der Filter darf nicht innerhalb eines Worts matchen
    assert "arbeitsagentur-1" in state.jobs


def test_exclude_keywords_matches_company_name(mocker, monkeypatch):
    """Filter greift auch auf Firma, nicht nur Titel."""
    j = _job("arbeitsagentur", "1").model_copy(update={
        "title": "Senior Consultant", "company": "Müller SPS GmbH",
    })
    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [j]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job")

    config = SearchesConfig(
        defaults=SearchDefaults(exclude_keywords=["SPS"]),
        searches=[SearchEntry(name="A", keywords=["x"], boards=["arbeitsagentur"])],
    )
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    assert state.jobs == {}


def test_no_exclude_keywords_no_filtering(mocker, monkeypatch):
    """Leere exclude_keywords -> Alle Jobs durchgereicht."""
    j1 = _job("arbeitsagentur", "1").model_copy(update={"title": "SPS Engineer"})
    j2 = _job("arbeitsagentur", "2").model_copy(update={"title": "KI Manager"})
    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = [j1, j2]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=Scoring(
        fit_score=7, begruendung="x", matched_skills=[], missing_skills=[],
        red_flags=[], verbessern_in_anschreiben=[],
    ))

    config = SearchesConfig(searches=[
        SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur"]),
    ])
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock())

    assert set(state.jobs.keys()) == {"arbeitsagentur-1", "arbeitsagentur-2"}


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


# ---------------------------------------------------------------------------
# Progress / Checkpoint / Cancel (Incident 2026-07-13: Run lief unsichtbar,
# unabbrechbar, und verlor bei Restart alle Ergebnisse)
# ---------------------------------------------------------------------------

def _fake_scoring():
    return Scoring(
        fit_score=5, begruendung="ok", matched_skills=[],
        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
    )


def _single_board_setup(mocker, monkeypatch, jobs):
    adapter = mocker.Mock()
    adapter.name = "arbeitsagentur"
    adapter.search.return_value = jobs
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    score = mocker.patch(
        "bewerber.discovery.orchestrator.score_job", return_value=_fake_scoring(),
    )
    config = SearchesConfig(searches=[
        SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur"]),
    ])
    return adapter, score, config


def test_discover_reports_progress_per_job(mocker, monkeypatch):
    jobs = [_job(ext="1"), _job(ext="2")]
    _, _, config = _single_board_setup(mocker, monkeypatch, jobs)

    seen = []
    discover(
        config, state=BewerberState(), master_yaml_text="m",
        llm=mocker.Mock(), progress=seen.append,
    )

    per_job = [p for p in seen if p.get("done")]
    assert per_job == [
        {"search": "A", "board": "arbeitsagentur", "done": 1, "total": 2,
         "source_idx": 1, "source_count": 1},
        {"search": "A", "board": "arbeitsagentur", "done": 2, "total": 2,
         "source_idx": 1, "source_count": 1},
    ]


def test_discover_checkpoints_state_after_each_board(mocker, monkeypatch):
    """Zwei Boards -> zwei Checkpoint-Aufrufe mit dem State (Zwischenspeichern)."""
    adapter_a = mocker.Mock()
    adapter_a.name = "arbeitsagentur"
    adapter_a.search.return_value = [_job("arbeitsagentur", "1")]
    adapter_b = mocker.Mock()
    adapter_b.name = "linkedin"
    adapter_b.search.return_value = [_job("linkedin", "2")]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter_a, "linkedin": adapter_b},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=_fake_scoring())

    config = SearchesConfig(searches=[
        SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur", "linkedin"]),
    ])
    state = BewerberState()
    checkpoints = mocker.Mock()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock(),
             checkpoint=checkpoints)

    assert checkpoints.call_count == 2
    checkpoints.assert_called_with(state)


def test_discover_cancel_stops_before_next_job(mocker, monkeypatch):
    """Cancel nach Job 1 -> Job 2+3 werden nicht mehr gescored, State behaelt Job 1."""
    import threading
    jobs = [_job(ext="1"), _job(ext="2"), _job(ext="3")]
    _, score, config = _single_board_setup(mocker, monkeypatch, jobs)

    cancel = threading.Event()
    state = BewerberState()
    discover(
        config, state=state, master_yaml_text="m", llm=mocker.Mock(),
        progress=lambda p: cancel.set(),  # Abbruch direkt nach dem ersten Job
        cancel=cancel,
    )

    assert score.call_count == 1
    assert "arbeitsagentur-1" in state.jobs
    assert "arbeitsagentur-2" not in state.jobs


def test_discover_cancel_before_start_skips_scrape(mocker, monkeypatch):
    """Bereits gesetztes Cancel -> gar kein Board-Scrape mehr."""
    import threading
    adapter, score, config = _single_board_setup(mocker, monkeypatch, [_job()])

    cancel = threading.Event()
    cancel.set()
    discover(config, state=BewerberState(), master_yaml_text="m",
             llm=mocker.Mock(), cancel=cancel)

    adapter.search.assert_not_called()
    score.assert_not_called()


def test_discover_cancelled_run_still_checkpoints(mocker, monkeypatch):
    """Auch beim Abbruch wird der bis dahin erreichte State gesichert."""
    import threading
    jobs = [_job(ext="1"), _job(ext="2")]
    _, _, config = _single_board_setup(mocker, monkeypatch, jobs)

    cancel = threading.Event()
    checkpoints = mocker.Mock()
    state = BewerberState()
    discover(
        config, state=state, master_yaml_text="m", llm=mocker.Mock(),
        progress=lambda p: cancel.set(), cancel=cancel, checkpoint=checkpoints,
    )

    checkpoints.assert_called_once_with(state)


def test_discover_per_board_limit_caps_scored_jobs(mocker, monkeypatch):
    """per_board_limit: hoechstens N Jobs pro Suche x Board werden gescored;
    das Limit wird auch an den Adapter durchgereicht (schnellerer Scrape)."""
    jobs = [_job(ext=str(i)) for i in range(8)]
    adapter, score, config = _single_board_setup(mocker, monkeypatch, jobs)

    seen = []
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock(),
             per_board_limit=3, progress=seen.append)

    assert score.call_count == 3
    assert len(state.jobs) == 3
    assert seen[-1]["total"] == 3
    assert adapter.search.call_args.kwargs.get("limit") == 3


def test_discover_sources_filter_limits_to_selected_combos(mocker, monkeypatch):
    """sources: nur ausgewaehlte Suche-x-Board-Kombis laufen; der
    Quellen-Zaehler im Progress spiegelt die Auswahl."""
    adapter_a = mocker.Mock()
    adapter_a.name = "arbeitsagentur"
    adapter_a.search.return_value = [_job("arbeitsagentur", "1")]
    adapter_b = mocker.Mock()
    adapter_b.name = "linkedin"
    adapter_b.search.return_value = [_job("linkedin", "2")]
    monkeypatch.setattr(
        "bewerber.discovery.orchestrator.scraper_registry",
        {"arbeitsagentur": adapter_a, "linkedin": adapter_b},
    )
    mocker.patch("bewerber.discovery.orchestrator.enrich_job", side_effect=lambda j: j)
    mocker.patch("bewerber.discovery.orchestrator.score_job", return_value=_fake_scoring())

    config = SearchesConfig(searches=[
        SearchEntry(name="A", keywords=["KI"], boards=["arbeitsagentur", "linkedin"]),
        SearchEntry(name="B", keywords=["PM"], boards=["arbeitsagentur"]),
    ])
    seen = []
    state = BewerberState()
    discover(config, state=state, master_yaml_text="m", llm=mocker.Mock(),
             progress=seen.append, sources=[("A", "linkedin")])

    adapter_a.search.assert_not_called()
    adapter_b.search.assert_called_once()
    assert list(state.jobs) == ["linkedin-2"]
    assert seen[-1]["source_idx"] == 1 and seen[-1]["source_count"] == 1
