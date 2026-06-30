from bewerber.shared.paths import Paths
from bewerber.shared.settings import UserSettings, load_settings, save_settings


def test_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    s = load_settings(Paths())
    assert s.default_template_set == "classic"


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    paths = Paths()
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    save_settings(paths, UserSettings(default_template_set="modern"))
    assert load_settings(paths).default_template_set == "modern"
