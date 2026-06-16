import pytest
from datetime import date
from pydantic import ValidationError
from bewerber.shared.state_schema import (
    RawJob, Scoring, JobStatus, StatusHistoryEntry, TrackedJob, BewerberState,
)


def test_scoring_coerces_string_to_list_for_verbessern_field():
    """Regression: Gemini liefert manchmal einen String statt einer Liste fuer
    verbessern_in_anschreiben/red_flags/etc. Schema muss das tolerant in [str] wandeln,
    sonst crashen Batch-Laeufe an Pydantic-Validation."""
    s = Scoring.model_validate({
        "fit_score": 6,
        "begruendung": "ok",
        "verbessern_in_anschreiben": "Betone die einzigartige Mischung aus IT-Projekten und Praxiserfahrung.",
    })
    assert s.verbessern_in_anschreiben == [
        "Betone die einzigartige Mischung aus IT-Projekten und Praxiserfahrung.",
    ]


def test_scoring_coerces_string_for_all_list_fields():
    s = Scoring.model_validate({
        "fit_score": 5, "begruendung": "x",
        "matched_skills": "Python",
        "missing_skills": "ITIL",
        "red_flags": "Vor-Ort-Zwang",
        "verbessern_in_anschreiben": "Beispiele zu KI nennen",
    })
    assert s.matched_skills == ["Python"]
    assert s.missing_skills == ["ITIL"]
    assert s.red_flags == ["Vor-Ort-Zwang"]
    assert s.verbessern_in_anschreiben == ["Beispiele zu KI nennen"]


def test_scoring_empty_string_becomes_empty_list():
    s = Scoring.model_validate({
        "fit_score": 5, "begruendung": "x",
        "matched_skills": "",
        "red_flags": "   ",
    })
    assert s.matched_skills == []
    assert s.red_flags == []


def test_scoring_keeps_normal_list_input():
    """Backward compat: Listen funktionieren weiter wie immer."""
    s = Scoring.model_validate({
        "fit_score": 7, "begruendung": "x",
        "matched_skills": ["Python", "n8n", "REFA"],
    })
    assert s.matched_skills == ["Python", "n8n", "REFA"]


def test_jobstatus_enum_has_expected_values():
    assert JobStatus.DISCOVERED.value == "discovered"
    assert JobStatus.SHORTLISTED.value == "shortlisted"
    assert JobStatus.TAILORED.value == "tailored"
    assert JobStatus.APPLIED.value == "applied"
    assert JobStatus.INTERVIEW.value == "interview"
    assert JobStatus.OFFER.value == "offer"
    assert JobStatus.REJECTED.value == "rejected"
    assert JobStatus.WITHDRAWN.value == "withdrawn"


def test_raw_job_minimal():
    job = RawJob(
        board="arbeitsagentur",
        external_id="10001-1003091744-S",
        url="https://example.com/job/1",
        title="KI Manager",
        company="ACME",
        location="Leipzig",
    )
    assert job.posted_date is None
    assert job.description is None


def test_scoring_clamps_fit_score():
    """fit_score must be 1-10."""
    with pytest.raises(ValidationError):
        Scoring(fit_score=0, begruendung="x", matched_skills=[], missing_skills=[], red_flags=[], verbessern_in_anschreiben=[])
    with pytest.raises(ValidationError):
        Scoring(fit_score=11, begruendung="x", matched_skills=[], missing_skills=[], red_flags=[], verbessern_in_anschreiben=[])
    ok = Scoring(fit_score=8, begruendung="passt", matched_skills=["n8n"], missing_skills=[], red_flags=[], verbessern_in_anschreiben=[])
    assert ok.fit_score == 8


def test_tracked_job_id_format():
    """job_id = '<board>-<external_id>' (computed property)."""
    raw = RawJob(board="linkedin", external_id="3401234567", url="https://x",
                 title="t", company="c", location="l")
    job = TrackedJob(raw=raw)
    assert job.job_id == "linkedin-3401234567"
    assert job.status == JobStatus.DISCOVERED


def test_tracked_job_round_trip_through_json():
    raw = RawJob(board="indeed", external_id="abc123", url="https://x",
                 title="t", company="c", location="l", posted_date=date(2026, 6, 1))
    scoring = Scoring(fit_score=7, begruendung="ok", matched_skills=["a"],
                     missing_skills=["b"], red_flags=[], verbessern_in_anschreiben=[])
    job = TrackedJob(
        raw=raw, scoring=scoring, status=JobStatus.APPLIED,
        status_history=[StatusHistoryEntry(status=JobStatus.DISCOVERED, at="2026-06-12T10:00:00")],
        application_link="https://applied.example",
        notes="Telefoniert mit Frau Müller am 13.06.",
    )
    payload = job.model_dump(mode="json")
    restored = TrackedJob.model_validate(payload)
    assert restored.status == JobStatus.APPLIED
    assert restored.raw.posted_date == date(2026, 6, 1)
    assert restored.scoring.fit_score == 7


def test_bewerber_state_holds_jobs_by_id():
    raw = RawJob(board="arbeitsagentur", external_id="x1", url="u", title="t",
                 company="c", location="l")
    state = BewerberState(
        schema_version=1,
        last_discovery_run=None,
        scrape_errors={},
        jobs={"arbeitsagentur-x1": TrackedJob(raw=raw)},
    )
    assert "arbeitsagentur-x1" in state.jobs
    assert state.jobs["arbeitsagentur-x1"].status == JobStatus.DISCOVERED
