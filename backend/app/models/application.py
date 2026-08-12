"""Application tracking database model."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import ApplicationStatus, ApplyMode


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

    # Relationships
    job: Mapped["Job"] = relationship(back_populates="applications")  # noqa: F821
    resume: Mapped["Resume | None"] = relationship(back_populates="applications")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Application(id={self.id}, job_id={self.job_id}, status='{self.status}')>"
