from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field, ConfigDict


VALID_BOARDS = Literal["arbeitsagentur", "linkedin", "indeed"]


class SearchDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locations: list[str] = Field(default_factory=list)
    date_posted_max_days: int = 14
    min_fit_score: int = 6
    # Globaler Ausschluss: matched (case-insensitive, Wortgrenze) gegen Titel + Firma
    # JEDES Suchresultats. Beispiel: ["SPS", "PLS"] → SPS-Programmierer + PLS-Engineer
    # werden vor dem Scoring rausgeworfen (spart LLM-Tokens).
    exclude_keywords: list[str] = Field(default_factory=list)


class SearchEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    keywords: list[str]
    boards: list[VALID_BOARDS]
    # Zusaetzlich zur globalen defaults.exclude_keywords-Liste. Vereinigung.
    exclude_keywords: list[str] = Field(default_factory=list)


class SearchesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defaults: SearchDefaults = Field(default_factory=SearchDefaults)
    searches: list[SearchEntry] = Field(default_factory=list)


def load_searches(path: Path) -> SearchesConfig:
    if not path.is_file():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SearchesConfig.model_validate(data)
