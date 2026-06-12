import re
from pathlib import Path
from playwright.sync_api import sync_playwright


def snapshot_url(url: str, out_dir: Path) -> str:
    """Open URL with headless Chromium, save HTML and printable PDF.

    Returns the extracted plain text (no HTML tags) for downstream LLM use.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            pdf_bytes = page.pdf(format="A4", margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"})
        finally:
            browser.close()

    (out_dir / "posting.html").write_text(html, encoding="utf-8")
    (out_dir / "posting.pdf").write_bytes(pdf_bytes)
    return _extract_text_from_html(html)


def _extract_text_from_html(html: str) -> str:
    """Strip tags + scripts + styles, decode nbsp/entities to plain text."""
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text
