from bewerber.tailoring.customize import (
    CustomizedResume,
    CustomBerufserfahrung,
    ProjekterfahrungBlock,
    SkillKategorien,
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


def _stub_response() -> CustomizedResume:
    return CustomizedResume(
        berufsprofil_zugespitzt="Tailored profil.",
        berufserfahrung=[
            CustomBerufserfahrung(
                position="PM",
                firma="Acme",
                von="2020-01",
                bis="2024-08",
                werdegang_bullets=["high-level a1", "high-level a2"],
                projekterfahrung=[
                    ProjekterfahrungBlock(
                        titel="Workflow-Automatisierung",
                        aufgaben=["b1", "b2"],
                        ergebnisse=["1,5 h/Tag → 10 min/Tag"],
                    ),
                ],
            ),
        ],
        skills_kategorisiert=SkillKategorien(
            projektmanagement=["Projektplanung"],
            automatisierung_ki=["n8n", "Python"],
        ),
    )


def test_customize_calls_llm_with_master_and_job(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = _stub_response()
    profile = _master()
    job_text = "KI Manager bei BMW. Python und Projekterfahrung gesucht."

    result = customize_resume(profile, job_text, llm=fake_llm)
    assert result.berufsprofil_zugespitzt.startswith("Tailored")
    assert result.berufserfahrung[0].projekterfahrung[0].titel == "Workflow-Automatisierung"
    assert "n8n" in result.skills_kategorisiert.automatisierung_ki

    args, kwargs = fake_llm.structured.call_args
    user_prompt = kwargs["user"]
    assert "KI Manager bei BMW" in user_prompt
    assert "Acme" in user_prompt  # master content in prompt
    assert kwargs["schema"] is CustomizedResume


def test_customize_filters_hidden_projects_from_prompt(mocker):
    """sichtbar_in_lebenslauf=False projects must not appear in the LLM prompt."""
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = _stub_response()
    profile = _master()
    customize_resume(profile, "job text", llm=fake_llm)
    user_prompt = fake_llm.structured.call_args.kwargs["user"]
    assert "1-x" in user_prompt  # visible
    assert "hidden" not in user_prompt  # hidden project not in prompt
    assert "2-y" not in user_prompt


def test_customize_passes_arbeitgeber_field_into_prompt(mocker):
    """Wenn ein Projekt einen `arbeitgeber` hat, muss dieser im Master-YAML im
    User-Prompt landen, damit die LLM die Zuordnung honorieren kann."""
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = _stub_response()
    profile = _master()
    # Tag das sichtbare Projekt mit einem expliziten Arbeitgeber
    profile.projekte[0].arbeitgeber = "Acme"
    customize_resume(profile, "job text", llm=fake_llm)
    user_prompt = fake_llm.structured.call_args.kwargs["user"]
    assert "arbeitgeber: Acme" in user_prompt


def test_customize_system_prompt_documents_arbeitgeber_rule(mocker):
    """Die System-Anweisung muss die Hard-Constraint erwaehnen, damit die LLM
    die `arbeitgeber`-Zuordnung nicht ignoriert."""
    from bewerber.tailoring.customize import CUSTOMIZE_SYSTEM_PROMPT
    assert "arbeitgeber" in CUSTOMIZE_SYSTEM_PROMPT
    assert "MÜSSEN" in CUSTOMIZE_SYSTEM_PROMPT or "verbindlich" in CUSTOMIZE_SYSTEM_PROMPT


def test_projekterfahrung_block_allows_empty_lists():
    """A theme block may have empty aufgaben/ergebnisse (defensive default)."""
    block = ProjekterfahrungBlock(titel="X")
    assert block.aufgaben == []
    assert block.ergebnisse == []


def test_skill_kategorien_default_empty():
    """All 5 categories default to empty lists."""
    sk = SkillKategorien()
    assert sk.prozessmanagement == []
    assert sk.projektmanagement == []
    assert sk.kommunikation_training == []
    assert sk.automatisierung_ki == []
    assert sk.vertrieb == []
