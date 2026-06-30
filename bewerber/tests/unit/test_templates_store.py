from bewerber.tailoring.templates_store import (
    BuiltinTemplateStore, TemplateChoice, DEFAULT_SET,
)


def test_store_lists_classic_and_modern():
    store = BuiltinTemplateStore()
    ids = {s.id for s in store.list_sets()}
    assert ids == {"classic", "modern"}
    assert store.has_set("classic") and store.has_set("modern")
    assert not store.has_set("gibtsnicht")


def test_store_template_path():
    store = BuiltinTemplateStore()
    assert store.template_path("classic", "lebenslauf") == "sets/classic/lebenslauf.html.j2"
    assert store.template_path("modern", "anschreiben") == "sets/modern/anschreiben.html.j2"


def test_template_choice_overrides_and_fallback():
    c = TemplateChoice(set_id="modern")
    assert c.cv() == "modern" and c.anschreiben() == "modern"
    c2 = TemplateChoice(set_id="modern", anschreiben_set="classic")
    assert c2.cv() == "modern" and c2.anschreiben() == "classic"
    assert DEFAULT_SET == "classic"
