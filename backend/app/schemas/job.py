"""Pydantic schemas for job-related API requests and responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SponsorConfidence


class JobSearchRequest(BaseModel):
    """Request body for multi-platform job search."""

    query: str = Field(..., min_length=1, max_length=500)
    location: str = ""
    # None (omitted) means "use the configured default fan-out"; an explicit [] means
    # "search nothing". A plain list default cannot express that difference — `[] or DEFAULT`
    # silently searched every registered source when the caller asked for none.
    platforms: list[str] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=20, ge=1, le=100)


class JobListingResponse(BaseModel):
    """Single job listing in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: str
    platform_job_id: str
    title: str
    company: str
    location: str
    url: str
    description: str
    salary_range: str | None = None
    job_type: str | None = None
    remote: bool = False
    posted_date: datetime | None = None
    experience_level: str | None = None
    match_score: float | None = None
    skills_required: dict | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    #: Structured intelligence lifted from the posting: the employer's own criteria labels,
    #: the requirement lines verbatim, benefits, and the experience bar it states.
    posting_data: dict | None = None
    #: When the full posting was fetched. ``None`` means never — which the UI must not render
    #: as "this job has no requirements".
    enriched_at: datetime | None = None
    #: How confident the system is this employer sponsors the Skilled Worker visa — see
    #: ``SponsorConfidence``. Computed and stored on every job, used for ranking, but until
    #: now never reached this response: the frontend had no way to show it per job.
    sponsor_confidence: SponsorConfidence = SponsorConfidence.UNKNOWN
    #: The matched register entry name, or the posting phrase that triggered detection.
    #: ``None`` for UNKNOWN — there is nothing to show, not a fact that was hidden.
    sponsor_evidence: str | None = None


class JobListResponse(BaseModel):
    """Paginated list of job listings."""

    items: list[JobListingResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


class JobAnalysisResponse(BaseModel):
    """Response for job analysis endpoint."""

    job_id: str
    match_score: float
    skill_match: float
    keyword_match: float
    missing_skills: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
