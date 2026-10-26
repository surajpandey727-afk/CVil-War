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
    #: ``None`` means "use my Apply mode setting". Every screen used to send ``review``, so the
    #: Settings and Onboarding choice of Autonomous never took effect.
    apply_mode: ApplyModeEnum | None = None


class ApplicationBatchCreate(BaseModel):
    """Request to create multiple job applications at once."""

    job_ids: list[str] = Field(..., min_length=1)
    resume_id: str | None = None
    #: ``None`` means "use my Apply mode setting" — see ApplicationCreate.
    apply_mode: ApplyModeEnum | None = None


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
    #: The Resume Intelligence structured version behind resume_id, if any — see
    #: models.application.Application.resume_version_id's own comment for why this carries
    #: no DB-level ForeignKey. Lets the frontend deep-link "this application used AI-PM v1.3"
    #: back to Resume Intelligence without a second lookup.
    resume_version_id: str | None = None
    status: str
    apply_mode: str
    #: How the application was actually delivered and whether the far end acknowledged it.
    #: Exposed so the UI never presents a simulated or unconfirmed run as a clean "Applied":
    #: ``status == applied`` with ``confirmation_state`` in {simulated, unconfirmed} is a real,
    #: distinct outcome the operator needs to see, not a success.
    submission_method: str = "none"
    confirmation_state: str = "pending"
    confirmation_detail: str | None = None
    ats_score: float | None = None
    cover_letter_path: str | None = None
    applied_at: datetime | None = None
    response_date: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    #: Which board the application goes through (the job's platform key, e.g. ``linkedin``)
    #: and where a person opens it. The Applications screen needs both to say what a row is
    #: actually waiting for ("your LinkedIn sign-in") and to offer "Open posting".
    portal: str | None = None
    application_url: str | None = None
    #: True once the owner approved it. An approval stands: review questions are not asked
    #: again, so the screen can say "approved - waiting for X" instead of looking stuck.
    approved: bool = False
    #: Set when a run stopped at a CAPTCHA/identity check (``captcha``). Approve or Resume
    #: retries it in a visible browser window on the automation host so the owner can clear it.
    blocked_reason: str | None = None


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
