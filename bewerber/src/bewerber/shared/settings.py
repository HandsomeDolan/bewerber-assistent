"""Per-User-Einstellungen (settings.yaml)."""
import os
import yaml
from pydantic import BaseModel, ConfigDict

from bewerber.shared.paths import Paths


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")  # vorwaertskompatibel
    default_template_set: str = "classic"


def load_settings(paths: Paths) -> UserSettings:
    p = paths.settings_yaml
    if not p.is_file():
        return UserSettings()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return UserSettings.model_validate(data)


def save_settings(paths: Paths, settings: UserSettings) -> None:
    p = paths.settings_yaml
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(settings.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, p)
