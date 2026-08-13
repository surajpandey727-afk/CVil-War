"""Application tracking database model."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import (
    ActionPriority,
    ApplicationHealth,
    ApplicationStatus,
    ApplyMode,
    ConfirmationState,
    NextAction,
    SubmissionMethod,
)


class Application(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A job application submitted or queued for submission."""

    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_application_status", "status"),
        Index("ix_application_job_id", "job_id"),
        # At most one ACTIVE application per (user, job): prevents duplicate auto-applies.
        # Terminal states (rejected/withdrawn/failed) are excluded so a user may re-apply.
        Index(
            "uq_app_active_job",
            "user_id",
            "job_id",
            unique=True,
            sqlite_where=text("status NOT IN ('rejected', 'withdrawn', 'failed')"),
            postgresql_where=text("status NOT IN ('rejected', 'withdrawn', 'failed')"),
        ),
    )

    # Foreign keys
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    resume_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Application state
    status: Mapped[ApplicationStatus] = mapped_column(
        pg_enum(ApplicationStatus, "application_status"),
        nullable=False,
        default=ApplicationStatus.QUEUED,
    )
    apply_mode: Mapped[ApplyMode] = mapped_column(
        pg_enum(ApplyMode, "apply_mode"), nullable=False, default=ApplyMode.REVIEW
    )

    # Scoring
    ats_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Documents
    cover_letter_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timestamps
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    browser_screenshots: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # -- Operational state (distinct from the hiring `status` above) --------------------
    #
    # An application can be at INTERVIEW and simultaneously BLOCKED because a session
    # expired. One column cannot carry both without losing the thing the command centre
    # exists to surface, so health and next_action are tracked separately.
    health: Mapped[ApplicationHealth] = mapped_column(
        pg_enum(ApplicationHealth, "application_health"),
        nullable=False,
        default=ApplicationHealth.HEALTHY,
    )
    next_action: Mapped[NextAction] = mapped_column(
        pg_enum(NextAction, "next_action"), nullable=False, default=NextAction.NONE
    )
    #: Plain-English reason the action is needed, shown verbatim in the queue.
    next_action_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_action_priority: Mapped[ActionPriority] = mapped_column(
        pg_enum(ActionPriority, "action_priority"), nullable=False, default=ActionPriority.NONE
    )
    #: Computed score used to order the queue; the reason string explains it to the user.
    next_action_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: Hard deadline driving urgency (assessment close, interview, response-by).
    action_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # -- Provenance (Job OS §1: one canonical record whatever the origin) ---------------
    #: How this application entered the system: discovery, sprint, manual, import, ats.
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="discovery")
    #: Platform the application actually lives on, when it differs from the discovery source.
    portal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: Where a human completes or reviews this application.
    application_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    #: Employer's own reference, when one is issued — used to reconcile external status.
    external_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # -- Submission evidence --------------------------------------------------------------
    #
    # Status alone cannot answer "did this actually reach anybody". A placeholder run with
    # ``BROWSER__LIVE_APPLY`` off left a row identical to a real confirmed submission, so
    # ``Applied`` meant "the pipeline ran" rather than "an employer received something".
    # These three columns make the difference explicit and auditable.

    submission_method: Mapped[SubmissionMethod] = mapped_column(
        pg_enum(SubmissionMethod, "submission_method"),
        nullable=False,
        default=SubmissionMethod.NONE,
        server_default=SubmissionMethod.NONE.value,
    )
    confirmation_state: Mapped[ConfirmationState] = mapped_column(
        pg_enum(ConfirmationState, "confirmation_state"),
        nullable=False,
        default=ConfirmationState.PENDING,
        server_default=ConfirmationState.PENDING.value,
    )
    #: What the agent actually reported, verbatim. Shown to the operator rather than
    #: summarised, because a paraphrase of a confirmation is not evidence of one.
    confirmation_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # -- Resume-from-position (Job OS §7/§8) ---------------------------------------------
    #: Where a paused application stopped, e.g. {"stage": "application_form",
    #: "completed": [...], "current": "work_authorisation", "remaining": [...]}.
    #: Persisted so a reconnect resumes at the current field instead of restarting.
    resume_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # -- Follow-up / assessment / interview tracking -------------------------------------
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_up_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assessment_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assessment_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Document version actually submitted. A version, never a document — see models/document.
    document_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Relationships
    job: Mapped["Job"] = relationship(back_populates="applications")  # noqa: F821
    resume: Mapped["Resume | None"] = relationship(back_populates="applications")  # noqa: F821
    events: Mapped[list["ApplicationEvent"]] = relationship(  # noqa: F821
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.occurred_at",
    )

    def __repr__(self) -> str:
        return f"<Application(id={self.id}, job_id={self.job_id}, status='{self.status}')>"
