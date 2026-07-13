import pytest
from bewerber.discovery.keyword_variants import (
    KeywordVariant,
    KeywordVariants,
    generate_keyword_variants,
    VARIANT_CATEGORIES,
)


def _fake_llm(mocker, variants):
    llm = mocker.Mock()
    llm.structured.return_value = KeywordVariants(variants=variants)
    return llm


def test_generates_and_passes_seeds_and_schema(mocker):
    llm = _fake_llm(mocker, [
        KeywordVariant(keyword="Project Manager", kategorie="Übersetzung"),
        KeywordVariant(keyword="Projektleiter", kategorie="Synonym"),
    ])
    result = generate_keyword_variants(["Projektmanager"], "", llm)
    assert [v.keyword for v in result.variants] == ["Project Manager", "Projektleiter"]

    _, kwargs = llm.structured.call_args
    assert kwargs["schema"] is KeywordVariants
    assert "Projektmanager" in kwargs["user"]


def test_description_flows_into_prompt(mocker):
    llm = _fake_llm(mocker, [KeywordVariant(keyword="Head of Delivery", kategorie="Senioritätsstufe")])
    generate_keyword_variants([], "strategische Rollen im Mittelstand", llm)
    _, kwargs = llm.structured.call_args
    assert "strategische Rollen im Mittelstand" in kwargs["user"]


def test_dedup_removes_seed_duplicates_case_insensitive(mocker):
    llm = _fake_llm(mocker, [
        KeywordVariant(keyword="projektmanager", kategorie="Schreibweise"),  # == seed
        KeywordVariant(keyword="Project Manager", kategorie="Übersetzung"),
    ])
    result = generate_keyword_variants(["Projektmanager"], "", llm)
    assert [v.keyword for v in result.variants] == ["Project Manager"]


def test_dedup_removes_internal_duplicates(mocker):
    llm = _fake_llm(mocker, [
        KeywordVariant(keyword="Project Manager", kategorie="Übersetzung"),
        KeywordVariant(keyword="PROJECT manager", kategorie="Schreibweise"),  # dup
    ])
    result = generate_keyword_variants(["Projektmanager"], "", llm)
    assert len(result.variants) == 1
    assert result.variants[0].keyword == "Project Manager"


def test_empty_input_raises_without_llm_call(mocker):
    llm = mocker.Mock()
    with pytest.raises(ValueError):
        generate_keyword_variants([], "   ", llm)
    llm.structured.assert_not_called()


def test_categories_constant_has_four_expected_values():
    assert VARIANT_CATEGORIES == ("Übersetzung", "Schreibweise", "Synonym", "Senioritätsstufe")
