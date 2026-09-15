"""Pydantic schemas for application-related API requests and responses."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Re-export the canonical enums (single source of truth: app.models.enums) under the
# names this module historically exposed, so existing importers keep working.
from app.models.enums import ApplicationStatus as StatusEnum
from app.models.enums import ApplyMode as ApplyModeEnum


class ApplicationCreate(BaseModel):
    """Request to create a single job application."""

    job_id: str
    resume_id: str | None = None
    apply_mode: ApplyModeEnum = ApplyModeEnum.REVIEW


class ApplicationBatchCreate(BaseModel):
    """Request to create multiple job applications at once."""

    job_ids: list[str] = Field(..., min_length=1)
    resume_id: str | None = None
    apply_mode: ApplyModeEnum = ApplyModeEnum.REVIEW


class ApplicationBulkApprove(BaseModel):
    """Request to approve and enqueue a set of staged (batch) applications."""

    application_ids: list[str] = Field(..., min_length=1)


class ApplicationStatusUpdate(BaseModel):
    """Request to update application status.

    ``resume_id`` is optional and independent of ``status`` — it exists so the "CV
    required" dashboard blocker (an application queued without a résumé chosen, or with
    one that's since been archived) can be resolved by re-sending the current status
    alongside the newly-picked résumé, without a separate endpoint.
    """

    status: StatusEnum
    notes: str | None = None
    resume_id: str | None = None


class ApplicationIntervention(BaseModel):
    """A user's response to a pending CAPTCHA/2FA intervention prompt."""

    response: str = Field(..., min_length=1, max_length=2000)


class ApplicationResponse(BaseModel):
    """Single application in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    # Populated from the related job for display (avoids the frontend showing opaque IDs).
    job_title: str | None = None
    company: str | None = None
    resume_id: str | None = None
    # Which CV actually went out. An id alone cannot answer that, and "what did they receive"
    # is the question a submitted application exists to answer.
    resume_name: str | None = None
    resume_type: str | None = None
    resume_ats_score: float | None = None
    #: True when that CV has since been archived. The application still points at it — this
    #: is why archiving exists instead of deletion.
    resume_archived: bool = False
    has_cover_letter: bool = False
    status: str
    apply_mode: str
    ats_score: float | None = None
    cover_letter_path: str | None = None
    applied_at: datetime | None = None
    response_date: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class CoverLetterResponse(BaseModel):
    """Result of generating a cover letter for an application."""

    application_id: str
    cover_letter_path: str | None = None


class ApplicationListResponse(BaseModel):
    """Paginated list of applications."""

    items: list[ApplicationResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
