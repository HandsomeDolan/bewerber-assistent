from pathlib import Path
from bewerber.tailoring.posting import JobPosting, read_posting_from_file


def test_jobposting_dataclass():
    p = JobPosting(
        title="KI Manager",
        firma="BMW",
        location="München",
        description="text",
        source_url=None,
        kontakt_name=None,
        kontakt_email=None,
    )
    assert p.title == "KI Manager"
    assert p.firma == "BMW"
    assert p.kontakt_email is None


def test_read_posting_from_txt(fixtures_dir: Path):
    p = read_posting_from_file(fixtures_dir / "sample_posting.txt")
    assert p.source_url is None
    assert "KI Produktmanager" in p.description
    assert "BMW Group" in p.description
    # title/firma/location not auto-parsed from raw text — kept None
    assert p.title is None or "KI" in (p.title or "")


def test_read_posting_from_pdf(fixtures_dir: Path):
    """PDF support reuses shared/document.py."""
    p = read_posting_from_file(fixtures_dir / "sample_resume.pdf")
    assert p.description  # non-empty


def test_read_posting_unsupported_format(tmp_path):
    f = tmp_path / "x.xyz"
    f.write_text("nope")
    try:
        read_posting_from_file(f)
    except ValueError as e:
        assert "unsupported" in str(e).lower() or "xyz" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")
