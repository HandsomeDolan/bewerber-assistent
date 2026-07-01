from bewerber.shared.theme_store import reserved_or_slug, RESERVED


def test_reserved_names_rejected():
    assert reserved_or_slug("Classic", set()) is None
    assert reserved_or_slug("modern", set()) is None
    assert reserved_or_slug("Base", set()) is None
    assert reserved_or_slug("   ", set()) is None  # leer


def test_normal_name_slugged():
    assert reserved_or_slug("Mein CV 2026", set()) == "Mein-CV-2026"


def test_duplicate_gets_suffix():
    existing = {"mein-cv"}
    out = reserved_or_slug("mein cv", existing)
    assert out and out != "mein-cv" and out.startswith("mein-cv")
    assert "classic" in RESERVED and "base" in RESERVED
