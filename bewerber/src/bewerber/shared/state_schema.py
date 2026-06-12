from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, computed_field


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
    board: str  # "arbeitsagentur" | "linkedin" | "indeed"
    external_id: str
    url: str
    title: str
    company: str
    location: str
    posted_date: Optional[date] = None
    description: Optional[str] = None
    description_hash: Optional[str] = None


class Scoring(BaseModel):
    """LLM scoring of a job against the master_profile."""
    model_config = ConfigDict(extra="forbid")
    fit_score: int = Field(ge=1, le=10, description="1 (kein Match) bis 10 (perfekt).")
    begruendung: str = Field(description="2-3 Sätze: warum dieser Score.")
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    verbessern_in_anschreiben: list[str] = Field(default_factory=list)


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


class BewerberState(BaseModel):
    """Top-level state.json contract."""
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    last_discovery_run: Optional[str] = None  # ISO 8601
    scrape_errors: dict[str, ScrapeError] = Field(default_factory=dict)
    jobs: dict[str, TrackedJob] = Field(default_factory=dict)
