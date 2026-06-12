from pathlib import Path
from bewerber.tailoring.snapshot import snapshot_url, _extract_text_from_html


def test_extract_text_strips_html_tags():
    html = "<html><body><h1>KI Manager</h1><p>Sie&nbsp;leiten...</p><script>x()</script></body></html>"
    text = _extract_text_from_html(html)
    assert "KI Manager" in text
    assert "Sie leiten" in text  # nbsp → space
    assert "<script>" not in text  # tags stripped
    assert "x()" not in text  # script content removed


def test_snapshot_url_writes_html_and_pdf(tmp_path, mocker):
    """Snapshot writes posting.html and posting.pdf via mocked Playwright."""

    fake_page = mocker.Mock()
    fake_page.content.return_value = "<html><body><h1>KI Manager</h1><p>Beschreibung</p></body></html>"
    fake_page.pdf.return_value = b"%PDF-fake"

    fake_browser = mocker.Mock()
    fake_browser.new_page.return_value = fake_page
    fake_browser.close = mocker.Mock()

    fake_pw = mocker.Mock()
    fake_pw.chromium.launch.return_value = fake_browser

    fake_ctx = mocker.MagicMock()
    fake_ctx.__enter__.return_value = fake_pw
    fake_ctx.__exit__.return_value = False

    mocker.patch("bewerber.tailoring.snapshot.sync_playwright", return_value=fake_ctx)

    out_dir = tmp_path / "snap"
    text = snapshot_url("https://example.com/job/123", out_dir)

    assert (out_dir / "posting.html").is_file()
    assert (out_dir / "posting.pdf").is_file()
    assert (out_dir / "posting.html").read_text(encoding="utf-8").startswith("<html>")
    assert (out_dir / "posting.pdf").read_bytes().startswith(b"%PDF")
    assert "KI Manager" in text
    assert "Beschreibung" in text
    fake_page.goto.assert_called_once_with("https://example.com/job/123", wait_until="domcontentloaded", timeout=30000)
