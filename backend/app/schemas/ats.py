"""API shapes for ATS evaluation: per-job scores, bulk scoring and per-application tailoring.

Scores are 0-1 on the wire (multiply by 100 to display), matching every other score in the API.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.application import ApplicationResponse
from app.schemas.resume import ResumeResponse


class TierSummary(BaseModel):
    matched: int = 0
    mentioned: int = 0
    total: int = 0


class MatchSummary(BaseModel):
    """The headline of one résumé-versus-job evaluation."""

    ats_match: float = Field(description="0-1")
    parsing: float
    shortlist: float
    band: str
    shortlist_band: str
    tiers: dict[str, TierSummary] = Field(default_factory=dict)
    top_gaps: list[str] = Field(
        default_factory=list, description="Critical requirements with no evidence"
    )
    constrained_by: list[str] = Field(default_factory=list)
    recruiter_signal: str = ""
    tailoring_limit: str = ""


class ScoredWith(BaseModel):
    resume_id: str
    resume_name: str
    #: "attached" (the application's own résumé), "chosen" (picked by the caller) or "best"
    #: (the best-matching of the user's base résumés).
    source: str


class ApplicationScoreItem(BaseModel):
    application_id: str
    job_id: str
    scored: bool
    #: Why nothing was scored (no job description, no résumé to score with, ...).
    reason: str = ""
    ats_score: float | None = None
    persisted: bool = False
    scored_with: ScoredWith | None = None
    summary: MatchSummary | None = None


class ApplicationScoreRequest(BaseModel):
    #: Omit to score every application waiting for review.
    application_ids: list[str] | None = Field(default=None, max_length=200)
    #: Score with this résumé instead of each application's own / the best base résumé.
    resume_id: str | None = None


class ApplicationScoreResponse(BaseModel):
    items: list[ApplicationScoreItem]
    scored: int
    skipped: int


class JobScoreItem(BaseModel):
    job_id: str
    scored: bool
    reason: str = ""
    match_score: float | None = None
    scored_with: ScoredWith | None = None
    top_gaps: list[str] = Field(default_factory=list)


class JobScoreRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=100)
    resume_id: str | None = None
    #: Re-score jobs that already have a score (after a résumé changed).
    force: bool = False


class JobScoreResponse(BaseModel):
    items: list[JobScoreItem]
    scored: int
    skipped: int


class ApplicationTailorRequest(BaseModel):
    #: The résumé to tailor. Omit to use the best-matching base résumé for this job.
    base_resume_id: str | None = None
    #: Generate a fresh version even if one already exists for this résumé and job.
    regenerate: bool = False


class ApplicationTailorResponse(BaseModel):
    application: ApplicationResponse
    resume: ResumeResponse
    #: ATS match of the base résumé and of the tailored file, from the generated PDF.
    ats_before: float | None = None
    ats_after: float | None = None
    status: str = ""
    target_note: str = ""
    summary: MatchSummary | None = None
