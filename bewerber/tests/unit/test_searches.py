import pytest
from pathlib import Path
from pydantic import ValidationError
from bewerber.discovery.searches import (
    SearchDefaults, SearchEntry, SearchesConfig, load_searches,
)


def test_search_entry_minimal():
    s = SearchEntry(name="KI Manager", keywords=["KI Manager"], boards=["arbeitsagentur"])
    assert s.name == "KI Manager"


def test_searches_config_rejects_unknown_board():
    with pytest.raises(ValidationError):
        SearchEntry(name="x", keywords=["a"], boards=["myspace"])


def test_load_searches_reads_yaml(tmp_path):
    p = tmp_path / "searches.yaml"
    p.write_text("""defaults:
  locations: [Leipzig]
  date_posted_max_days: 7
  min_fit_score: 5
searches:
  - name: KI Manager
    keywords: [KI Manager, AI PM]
    boards: [arbeitsagentur, linkedin]
""")
    cfg = load_searches(p)
    assert cfg.defaults.locations == ["Leipzig"]
    assert cfg.defaults.date_posted_max_days == 7
    assert len(cfg.searches) == 1
    assert cfg.searches[0].keywords == ["KI Manager", "AI PM"]


def test_load_searches_missing_file(tmp_path):
    p = tmp_path / "nope.yaml"
    with pytest.raises(FileNotFoundError):
        load_searches(p)


def test_load_searches_invalid_yaml_raises(tmp_path):
    p = tmp_path / "searches.yaml"
    p.write_text("not: valid\n  : structure")
    with pytest.raises(Exception):
        load_searches(p)
