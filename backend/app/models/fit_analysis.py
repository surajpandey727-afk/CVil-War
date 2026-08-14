"""A stored job-vs-CV fit assessment.

Keyed on ``(job_id, resume_id)`` because that pair is what determines the answer: the same
job assessed against a different CV is a different assessment, and the product has to be able
to say so rather than showing one and implying the other.

The full report lives in ``payload`` as JSON. It is a snapshot of a computation, not an entity
with its own lifecycle — nothing queries inside it, and promoting its fields to columns would
mean a migration every time the report gains a section. ``overall`` and ``method`` are
promoted because they are the two things a list view needs without deserialising everything.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class FitAnalysisRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One CV assessed against one job."""

    __tablename__ = "fit_analyses"
    __table_args__ = (
        # One current answer per pair. Superseded scores are replaced, not accumulated —
        # keeping a history would only invite the UI to show a stale one.
        Index("uq_fit_job_resume", "user_id", "job_id", "resume_id", unique=True),
    )

    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: SET NULL rather than CASCADE: deleting a CV should not erase the record that this job
    #: was assessed, and the payload still carries the CV's name at the time.
    resume_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    overall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: ``llm`` or ``keyword`` — a degraded analysis must stay identifiable after storage.
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="keyword")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    analysed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<FitAnalysisRecord(job={self.job_id}, resume={self.resume_id}, {self.overall})>"
