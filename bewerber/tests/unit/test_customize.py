from bewerber.tailoring.customize import (
    CustomizedResume,
    CustomBerufserfahrung,
    CustomProject,
    customize_resume,
)
from bewerber.shared.profile_schema import MasterProfile, Person, Berufserfahrung, Project


def _master() -> MasterProfile:
    return MasterProfile(
        person=Person(name="Steve", email="s@x.de"),
        berufsprofil="Erfahrener Manager.",
        zielposition=["KI Manager"],
        ausbildung=[],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01", bis="2024-08",
                            aufgaben=["a1", "a2"], erfolge=["e1"], skills=["s1"]),
            Berufserfahrung(position="Engineer", firma="Old", von="2015-01", bis="2019-12",
                            aufgaben=["o1"], erfolge=[], skills=["s2"]),
        ],
        projekte=[
            Project(id="1-x", titel="X", kurzbeschreibung="kb", rolle="r",
                    skills_fachlich=["Python"], sichtbar_in_lebenslauf=True),
            Project(id="2-y", titel="Y", kurzbeschreibung="hidden", rolle="r",
                    skills_fachlich=["X"], sichtbar_in_lebenslauf=False),
        ],
    )


def test_customize_calls_llm_with_master_and_job(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = CustomizedResume(
        berufsprofil_zugespitzt="Tailored profil.",
        berufserfahrung=[
            CustomBerufserfahrung(position="PM", firma="Acme", von="2020-01", bis="2024-08",
                                   aufgaben=["a1 (geschärft)", "a2"], erfolge=["e1"], skills=["s1"]),
        ],
        projekte_hervorheben=["1-x"],
        skills_reihenfolge=["s1", "Python"],
    )
    profile = _master()
    job_text = "KI Manager bei BMW. Python und Projekterfahrung gesucht."

    result = customize_resume(profile, job_text, llm=fake_llm)
    assert result.berufsprofil_zugespitzt.startswith("Tailored")
    assert result.projekte_hervorheben == ["1-x"]

    args, kwargs = fake_llm.structured.call_args
    user_prompt = kwargs["user"]
    assert "KI Manager bei BMW" in user_prompt
    assert "Acme" in user_prompt  # master content in prompt
    assert kwargs["schema"] is CustomizedResume


def test_customize_filters_hidden_projects_from_prompt(mocker):
    """sichtbar_in_lebenslauf=False projects must not appear in the LLM prompt."""
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = CustomizedResume(
        berufsprofil_zugespitzt="X.",
        berufserfahrung=[],
        projekte_hervorheben=[],
        skills_reihenfolge=[],
    )
    profile = _master()
    customize_resume(profile, "job text", llm=fake_llm)
    user_prompt = fake_llm.structured.call_args.kwargs["user"]
    assert "1-x" in user_prompt  # visible
    assert "hidden" not in user_prompt  # hidden project not in prompt
    assert "2-y" not in user_prompt
