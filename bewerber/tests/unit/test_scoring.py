from bewerber.discovery.scoring import score_job
from bewerber.shared.state_schema import RawJob, Scoring


def _job(description="Beschreibung zur Stelle.") -> RawJob:
    return RawJob(
        board="arbeitsagentur", external_id="1",
        url="https://x", title="KI Manager", company="BMW",
        location="München", description=description,
    )


def test_score_job_returns_scoring_from_llm(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = Scoring(
        fit_score=8,
        begruendung="Profil passt zu KI/Workflow-Schwerpunkt.",
        matched_skills=["n8n", "Python"],
        missing_skills=["SAP"],
        red_flags=[],
        verbessern_in_anschreiben=["SAP-Erfahrung framen"],
    )
    result = score_job(
        job=_job(),
        master_yaml_text="person:\n  name: Steve",
        llm=fake_llm,
    )
    assert isinstance(result, Scoring)
    assert result.fit_score == 8
    assert "n8n" in result.matched_skills

    args, kwargs = fake_llm.structured.call_args
    user_prompt = kwargs["user"]
    assert "KI Manager" in user_prompt
    assert "BMW" in user_prompt
    assert "Beschreibung zur Stelle" in user_prompt
    assert "Steve" in user_prompt  # master profile in prompt
    assert kwargs["schema"] is Scoring


def test_score_job_uses_title_company_when_description_missing(mocker):
    """Even without description, scoring still works on title+company."""
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = Scoring(
        fit_score=5, begruendung="x", matched_skills=[],
        missing_skills=[], red_flags=[], verbessern_in_anschreiben=[],
    )
    job = _job(description=None)
    score_job(job=job, master_yaml_text="x", llm=fake_llm)
    user_prompt = fake_llm.structured.call_args.kwargs["user"]
    assert "KI Manager" in user_prompt
    assert "(keine ausführliche Beschreibung verfügbar)" in user_prompt
