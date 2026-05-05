from pathlib import Path
from bewerber.profile.extractor import (
    ExtractedProfile,
    extract_profile_from_documents,
)
from bewerber.shared.profile_schema import (
    Person,
    Ausbildung,
    Berufserfahrung,
    Zertifikat,
    Sprache,
)


def test_extract_profile_calls_llm_with_document_texts(tmp_path, mocker):
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    (docs_dir / "Lebenslauf.pdf").write_bytes(b"%PDF-1.4 fake")
    (docs_dir / "Zeugnis.pdf").write_bytes(b"%PDF-1.4 fake")

    mocker.patch(
        "bewerber.profile.extractor.read_document_text",
        side_effect=lambda p: f"text-of-{p.name}",
    )

    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ExtractedProfile(
        person=Person(name="Steve", email="s@x.de"),
        berufsprofil="kurz",
        zielposition=["KI Manager"],
        ausbildung=[Ausbildung(art="Techniker", institution="X")],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01", bis=None)
        ],
        zertifikate=[Zertifikat(name="REFA")],
        sprachen=[Sprache(sprache="Deutsch", niveau="Muttersprache")],
        interessen=["KI"],
    )

    profile = extract_profile_from_documents(docs_dir, llm=fake_llm)
    assert profile.person.name == "Steve"
    assert profile.berufserfahrung[0].firma == "Acme"

    args, kwargs = fake_llm.structured.call_args
    user_text = kwargs["user"]
    assert "Lebenslauf.pdf" in user_text
    assert "text-of-Lebenslauf.pdf" in user_text
    assert "text-of-Zeugnis.pdf" in user_text


def test_extract_skips_unsupported_files(tmp_path, mocker):
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    (docs_dir / "doc.pdf").write_bytes(b"x")
    (docs_dir / "ignored.jpg").write_bytes(b"x")
    (docs_dir / ".DS_Store").write_bytes(b"x")
    (docs_dir / "Bewerbungen").mkdir()
    (docs_dir / "Bewerbungen" / "alte.docx").write_bytes(b"x")  # subfolder excluded

    captured: list[str] = []
    mocker.patch(
        "bewerber.profile.extractor.read_document_text",
        side_effect=lambda p: (captured.append(p.name) or "x"),
    )
    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ExtractedProfile(
        person=Person(name="X", email="x@y.de"),
        berufsprofil="k",
        zielposition=[],
        ausbildung=[],
        berufserfahrung=[],
        zertifikate=[],
        sprachen=[],
        interessen=[],
    )
    extract_profile_from_documents(docs_dir, llm=fake_llm)
    assert captured == ["doc.pdf"]


from bewerber.profile.extractor import save_anschreiben_examples


def test_save_anschreiben_examples_writes_text_files(tmp_path, mocker):
    src1 = tmp_path / "Anschreiben_A.docx"
    src2 = tmp_path / "Anschreiben_B.pdf"
    src1.write_bytes(b"x")
    src2.write_bytes(b"x")

    mocker.patch(
        "bewerber.profile.extractor.read_document_text",
        side_effect=lambda p: f"INHALT VON {p.name}",
    )

    out_dir = tmp_path / "examples"
    saved = save_anschreiben_examples([src1, src2], out_dir)
    assert len(saved) == 2
    assert saved[0].suffix == ".txt"
    assert saved[0].read_text(encoding="utf-8") == "INHALT VON Anschreiben_A.docx"
    assert saved[1].read_text(encoding="utf-8") == "INHALT VON Anschreiben_B.pdf"


def test_save_anschreiben_examples_creates_dir(tmp_path, mocker):
    src = tmp_path / "X.docx"
    src.write_bytes(b"x")
    mocker.patch("bewerber.profile.extractor.read_document_text", return_value="text")
    out_dir = tmp_path / "deep" / "nested" / "examples"
    saved = save_anschreiben_examples([src], out_dir)
    assert out_dir.is_dir()
    assert saved[0].parent == out_dir


def test_extract_truncates_huge_document_set(tmp_path, mocker):
    from bewerber.profile.extractor import MAX_TOTAL_CHARS
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    # 5 fake docs each "containing" 100k chars of text → total 500k > MAX_TOTAL_CHARS
    for i in range(5):
        (docs_dir / f"doc{i}.pdf").write_bytes(b"x")

    mocker.patch(
        "bewerber.profile.extractor.read_document_text",
        side_effect=lambda p: "X" * 100_000,
    )

    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ExtractedProfile(
        person=Person(name="X", email="x@y.de"),
        berufsprofil="k",
        zielposition=[],
        ausbildung=[],
        berufserfahrung=[],
        zertifikate=[],
        sprachen=[],
        interessen=[],
    )
    extract_profile_from_documents(docs_dir, llm=fake_llm)

    args, kwargs = fake_llm.structured.call_args
    user_text = kwargs["user"]
    assert len(user_text) <= MAX_TOTAL_CHARS + 1000  # allow some header overhead
    # Last doc should show as skipped or be truncated
    assert "Token-Budget" in user_text or len(user_text) <= MAX_TOTAL_CHARS + 1000
