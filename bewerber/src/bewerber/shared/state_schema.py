from datetime import date
from enum import Enum
from typing import Annotated, Optional
from pydantic import BaseModel, BeforeValidator, Field, ConfigDict, computed_field


def _coerce_str_to_list(value):
    """Manche LLMs (Gemini insbesondere) returnen einen String fuer list[str]-Felder.
    Statt ValidationError zu werfen, wrappen wir den String in ein 1-Element-Array.
    Leere/whitespace-only Strings werden zu []. Listen bleiben unveraendert.
    """
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return value


_ListOfStr = Annotated[list[str], BeforeValidator(_coerce_str_to_list)]


class JobStatus(str, Enum):
    DISCOVERED = "discovered"
    SHORTLISTED = "shortlisted"
    TAILORED = "tailored"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class RawJob(BaseModel):
    """A job posting as fetched from a board. Description may be None until enriched."""
    model_config = ConfigDict(extra="forbid")
    board: str  # "arbeitsagentur" | "linkedin" | "indeed" | "manual"
    external_id: str
    url: str
    title: str
    company: str
    location: str
    posted_date: Optional[date] = None
    description: Optional[str] = None
    description_hash: Optional[str] = None
    # Aus der Beschreibung extrahiertes Arbeitsmodell: "remote" oder "hybrid".
    # None = nichts erkannt oder klassisch vor Ort (wird im UI nicht angezeigt).
    arbeitsmodell: Optional[str] = None


class Scoring(BaseModel):
    """LLM scoring of a job against the master_profile."""
    model_config = ConfigDict(extra="forbid")
    fit_score: int = Field(ge=1, le=10, description="1 (kein Match) bis 10 (perfekt).")
    begruendung: str = Field(description="2-3 Sätze: warum dieser Score.")
    # _ListOfStr wrappt einen String automatisch in [String], falls die LLM
    # statt eines Arrays einen einzelnen Hinweis als String zurueckliefert.
    matched_skills: _ListOfStr = Field(default_factory=list)
    missing_skills: _ListOfStr = Field(default_factory=list)
    red_flags: _ListOfStr = Field(default_factory=list)
    verbessern_in_anschreiben: _ListOfStr = Field(default_factory=list)


class StatusHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: JobStatus
    at: str  # ISO 8601 timestamp


class TrackedJob(BaseModel):
    """A job in state.json with optional scoring, status workflow, tailored output linkage."""
    model_config = ConfigDict(extra="forbid")
    raw: RawJob
    scoring: Optional[Scoring] = None
    status: JobStatus = JobStatus.DISCOVERED
    status_history: list[StatusHistoryEntry] = Field(default_factory=list)
    first_seen: Optional[str] = None  # ISO 8601 timestamp
    tailored_dir: Optional[str] = None  # path to Bewerbungsordner once tailored
    application_link: Optional[str] = None  # URL to the submitted application (recruiter portal etc.)
    interview_scheduled: Optional[str] = None  # ISO 8601
    notes: str = ""

    @computed_field(exclude_if=lambda v: True)
    @property
    def job_id(self) -> str:
        return f"{self.raw.board}-{self.raw.external_id}"


class ScrapeError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    last_error: str
    at: str  # ISO 8601


class FailedUrl(BaseModel):
    """URL aus einem Batch-Run, die nicht verarbeitet werden konnte.

    Bleibt in state.json bis sie erfolgreich nachgereicht oder per UI
    verworfen wird.
    """
    model_config = ConfigDict(extra="forbid")
    url: str
    error: str
    at: str  # ISO 8601


class BewerberState(BaseModel):
    """Top-level state.json contract."""
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    last_discovery_run: Optional[str] = None  # ISO 8601
    scrape_errors: dict[str, ScrapeError] = Field(default_factory=dict)
    jobs: dict[str, TrackedJob] = Field(default_factory=dict)
    failed_urls: list[FailedUrl] = Field(default_factory=list)
