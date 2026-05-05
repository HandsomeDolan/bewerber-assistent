from pathlib import Path
from bewerber.shared.document import read_document_text


def test_read_pdf(fixtures_dir: Path):
    text = read_document_text(fixtures_dir / "sample_resume.pdf")
    assert "Steve Eigenwillig" in text
    assert "s.eigenwillig@example.com" in text


def test_read_docx(fixtures_dir: Path):
    text = read_document_text(fixtures_dir / "sample.docx")
    assert "Sehr geehrte Damen und Herren" in text
    assert "Projektmanager" in text


def test_unsupported_format_raises(tmp_path):
    f = tmp_path / "x.xyz"
    f.write_text("nope")
    try:
        read_document_text(f)
    except ValueError as e:
        assert "unsupported" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")


def test_missing_file_raises(tmp_path):
    try:
        read_document_text(tmp_path / "nope.pdf")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")
