from bewerber.shared.paths import Paths
from bewerber.shared.theme import Theme
from bewerber.shared.theme_store import save_theme, load_theme, list_themes, delete_theme
from bewerber.tailoring.templates_store import UserTemplateStore


def test_theme_roundtrip_and_store(tmp_path, monkeypatch):
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    paths = Paths()
    save_theme(paths, Theme(id="mycv", name="Mein CV", accent_color="#abcdef"))
    assert load_theme(paths, "mycv").accent_color == "#abcdef"
    assert [t.id for t in list_themes(paths)] == ["mycv"]

    store = UserTemplateStore(paths)
    ids = {s.id for s in store.list_sets()}
    assert {"classic", "modern", "mycv"} <= ids
    assert store.has_set("mycv") and store.template_path("mycv", "lebenslauf") == "sets/base/lebenslauf.html.j2"
    assert store.theme_tokens("mycv")["accent_color"] == "#abcdef"
    assert store.theme_tokens("classic") is None       # builtin -> keine Tokens
    assert store.template_path("classic", "lebenslauf") == "sets/classic/lebenslauf.html.j2"

    assert delete_theme(paths, "mycv") is True
    assert load_theme(paths, "mycv") is None
