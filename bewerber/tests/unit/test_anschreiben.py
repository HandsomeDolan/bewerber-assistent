from pathlib import Path
from bewerber.tailoring.anschreiben import AnschreibenContent, generate_anschreiben, _collect_few_shot_examples


def test_collect_examples_returns_empty_when_dir_missing(tmp_path):
    examples = _collect_few_shot_examples(tmp_path / "nope")
    assert examples == []


def test_collect_examples_reads_txt_files_in_order(tmp_path):
    d = tmp_path / "examples"
    d.mkdir()
    (d / "02_lead.txt").write_text("Anschreiben Lead PM ...")
    (d / "01_ki.txt").write_text("Anschreiben KI Manager ...")
    examples = _collect_few_shot_examples(d)
    assert len(examples) == 2
    assert examples[0].startswith("Anschreiben KI")  # 01 first
    assert examples[1].startswith("Anschreiben Lead")


def test_generate_anschreiben_calls_llm_with_master_and_job(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = AnschreibenContent(
        anrede="Sehr geehrte Frau Müller,",
        einleitung="Mit großem Interesse...",
        hauptteil="Meine Erfahrung als Projektmanager...",
        schluss="Über die Einladung würde ich mich freuen.",
        gruss="Mit freundlichen Grüßen\nSteve Eigenwillig",
    )
    result = generate_anschreiben(
        master_yaml_text="person:\n  name: Steve",
        job_description="KI Manager bei BMW",
        kontakt_name="Anna Müller",
        few_shot_examples=["Beispiel-Anschreiben 1 ..."],
        llm=fake_llm,
    )
    assert result.anrede.startswith("Sehr geehrte")
    assert "Müller" in result.anrede

    args, kwargs = fake_llm.structured.call_args
    user_prompt = kwargs["user"]
    assert "KI Manager bei BMW" in user_prompt
    assert "Anna Müller" in user_prompt
    assert "Beispiel-Anschreiben 1" in user_prompt
    assert kwargs["schema"] is AnschreibenContent


def test_generate_anschreiben_falls_back_when_kontakt_missing(mocker):
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = AnschreibenContent(
        anrede="Sehr geehrte Damen und Herren,",
        einleitung="x", hauptteil="x", schluss="x",
        gruss="Mit freundlichen Grüßen\nSteve",
    )
    result = generate_anschreiben(
        master_yaml_text="x",
        job_description="y",
        kontakt_name=None,
        few_shot_examples=[],
        llm=fake_llm,
    )
    user_prompt = fake_llm.structured.call_args.kwargs["user"]
    assert "kein konkreter Ansprechpartner" in user_prompt.lower() or "damen und herren" in user_prompt.lower()


def test_anschreiben_to_markdown():
    content = AnschreibenContent(
        anrede="Sehr geehrte Frau Müller,",
        einleitung="E1.",
        hauptteil="H1.\n\nH2.",
        schluss="S1.",
        gruss="Mit freundlichen Grüßen\nSteve",
    )
    md = content.to_markdown()
    assert "Sehr geehrte Frau Müller," in md
    assert "E1." in md
    assert "H1." in md
    assert "S1." in md
    assert "Mit freundlichen Grüßen" in md
