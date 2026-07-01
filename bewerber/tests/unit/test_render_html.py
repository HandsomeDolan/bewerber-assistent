from bewerber.dashboard.sample_data import preview_html, SAMPLE_PROFILE
from bewerber.shared.theme import Theme
from bewerber.tailoring import render_html


def test_render_html_importable_without_weasyprint():
    # render_html darf KEIN weasyprint importieren (sonst lokal nicht ladbar)
    import sys
    assert "weasyprint" not in getattr(render_html, "__dict__", {})


def test_preview_html_applies_theme():
    tokens = Theme(id="t", name="T", accent_color="#abcdef").tokens()
    html = preview_html(tokens)
    assert "Alex Beispiel" in html and "#abcdef" in html and "set: base" in html


def test_preview_html_default_tokens():
    html = preview_html(None)
    assert "set: base" in html and "#1f6feb" in html  # Default-Akzent
