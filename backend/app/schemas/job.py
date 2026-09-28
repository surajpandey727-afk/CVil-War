"""Pydantic schemas for job-related API requests and responses."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.salary import parse_salary
from app.models.enums import JobStatus, SponsorConfidence

#: The vocabulary a candidate filters by. Deliberately three values, not five: the evidence
#: grades behind ``SponsorConfidence`` answer "how do we know", which is a different question
#: from "can I take this job", and a filter offering five overlapping options is one nobody
#: uses correctly.
SponsorshipStatus = Literal["available", "not_specified", "none"]


def sponsorship_status(confidence: SponsorConfidence | str) -> SponsorshipStatus:
    """Collapse the evidence grade into the answer a visa-dependent candidate needs.

    ``LIKELY`` counts as available even though nothing currently classifies into it: if a
    future signal ever does, the honest place for it is alongside the other positives, not
    silently in with the postings that said nothing.
    """
    value = confidence.value if isinstance(confidence, SponsorConfidence) else str(confidence)
    if value in {
        SponsorConfidence.CONFIRMED_REGISTER.value,
        SponsorConfidence.KEYWORD_DETECTED.value,
        SponsorConfidence.LIKELY.value,
    }:
        return "available"
    if value == SponsorConfidence.NOT_SPONSOR.value:
        return "none"
    return "not_specified"


class JobSearchRequest(BaseModel):
    """Request body for multi-platform job search."""

    # The frontend's default query is every active role-target title joined with ", " —
    # 500 was sized for a hand-typed search box, not a generated list. 31 default titles
    # alone run to ~690 chars; a 500-char cap 422'd every default search before it ran,
    # which looked like "job discovery is completely broken" from the UI (nothing to
    # select, nothing to preview) with no visible error. 2000 comfortably covers the
    # current default list with headroom for a user adding more targets.
    query: str = Field(..., min_length=1, max_length=2000)
    location: str = ""
    # None (omitted) means "use the configured default fan-out"; an explicit [] means
    # "search nothing". A plain list default cannot express that difference — `[] or DEFAULT`
    # silently searched every registered source when the caller asked for none.
    platforms: list[str] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=20, ge=1, le=100)


class JobStatusUpdate(BaseModel):
    """Request to save, hide, or otherwise change a job's lifecycle status."""

    status: JobStatus


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

    # -- Canonical, filterable form of the two facts candidates actually filter on ---------
    #
    # ``salary_range`` is free text and ``sponsor_confidence`` is a five-way evidence grade;
    # neither can be compared or bucketed without being read first. Serving the read form means
    # the filter, the sort and the card all use the same numbers. They previously each derived
    # their own, and disagreed: a card showing "£60,000" was filtered out by a £50k minimum
    # because the filter had read the "10% bonus" in the same string as £10k.
    salary_min: int | None = None
    salary_max: int | None = None
    #: ISO code when the posting marked one, else ``None`` — never assumed to be GBP.
    salary_currency: str | None = None
    #: ``year`` unless the posting quoted a day, hour or monthly rate.
    salary_period: str | None = None
    #: True when the figures were converted from a non-annual rate, so the UI can say so
    #: rather than presenting a derived number as the employer's own.
    salary_annualised: bool = False
    #: The three states a candidate needs a visa filter to distinguish. Any positive evidence
    #: is ``available``; an explicit refusal is ``none``; silence is ``not_specified`` — which
    #: is the common case and must never be collapsed into either of the others.
    sponsorship_status: SponsorshipStatus = "not_specified"

    @model_validator(mode="after")
    def _derive_canonical_fields(self) -> "JobListingResponse":
        band = parse_salary(self.salary_range)
        self.salary_min = band.minimum
        self.salary_max = band.maximum
        self.salary_currency = band.currency
        self.salary_period = band.period
        self.salary_annualised = band.annualised
        self.sponsorship_status = sponsorship_status(self.sponsor_confidence)
        return self


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
