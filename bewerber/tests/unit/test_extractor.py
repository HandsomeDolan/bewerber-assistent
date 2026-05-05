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
