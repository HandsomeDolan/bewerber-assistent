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


def test_read_docx_includes_table_cells(fixtures_dir: Path):
    text = read_document_text(fixtures_dir / "sample_with_tables.docx")
    assert "2020-2024" in text
    assert "Projektmanager bei Magna" in text
    assert "2016-2020" in text
    assert "Entwickler bei Acme GmbH" in text


def test_read_docx_includes_header_footer(fixtures_dir: Path):
    text = read_document_text(fixtures_dir / "sample_with_tables.docx")
    assert "Steve Eigenwillig — Lebenslauf" in text
    assert "Seite 1 von 1" in text


def test_read_docx_preserves_body_paragraphs_alongside_tables(fixtures_dir: Path):
    text = read_document_text(fixtures_dir / "sample_with_tables.docx")
    assert "Berufserfahrung:" in text
