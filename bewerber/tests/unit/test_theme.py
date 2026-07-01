import pytest
from bewerber.shared.theme import Theme, SectionKey, map_font, FONT_WHITELIST, DEFAULT_THEME_TOKENS


def test_defaults_valid():
    t = Theme(id="t1", name="T1")
    assert t.font_family in FONT_WHITELIST
    assert t.accent_color.startswith("#") and len(t.accent_color) == 7
    assert t.header_style == "left_accent_bar"
    assert set(t.section_order) == set(s.value for s in SectionKey)


def test_bad_color_falls_back_to_default():
    t = Theme(id="t1", name="T1", accent_color="red; } body{display:none")
    assert t.accent_color == "#1f6feb"  # Default, keine Injection


def test_font_mapped_to_whitelist():
    assert map_font("Calibri Light") == "calibri"
    assert map_font("Arially McArialface") == "calibri"  # unbekannt -> Default
    t = Theme(id="t1", name="T1", font_family="TimesNewRoman")
    assert t.font_family in FONT_WHITELIST


def test_section_order_normalized():
    # Duplikate + fehlende Sektionen: dedupe + fehlende ans Ende
    t = Theme(id="t1", name="T1", section_order=["skills", "skills", "profil"])
    assert t.section_order[:2] == ["skills", "profil"]
    assert set(t.section_order) == set(s.value for s in SectionKey)
    assert len(t.section_order) == len(set(t.section_order))


def test_default_tokens_render_ready():
    assert DEFAULT_THEME_TOKENS["accent_color"] == "#1f6feb"
    assert "font_stack" in DEFAULT_THEME_TOKENS
