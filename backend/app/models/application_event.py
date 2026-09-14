"""Append-only timeline for an application.

Every meaningful state change writes a row here. The application row holds the *current*
state; this holds how it got there — which is what lets the command centre answer "what
happened to this application" without inferring it from timestamps scattered across columns.

Append-only by convention: rows are never updated or deleted, so the timeline is a faithful
record even when a state is later corrected.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import ApplicationEventType


class ApplicationEvent(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One entry on an application's timeline."""

    __tablename__ = "application_events"
    __table_args__ = (
        # The timeline is always read newest-or-oldest-first for one application.
        Index("ix_app_event_app_occurred", "application_id", "occurred_at"),
        Index("ix_app_event_type", "event_type"),
    )

    application_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[ApplicationEventType] = mapped_column(
        pg_enum(ApplicationEventType, "application_event_type"), nullable=False
    )
    #: When the thing happened, which is not always when the row was written — an imported
    #: application backfills historical events with their real dates.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Free-form payload: previous/next status, document id, deadline, source of a change.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: "system", "user", "worker", or a platform key — who caused this.
    actor: Mapped[str] = mapped_column(String(50), nullable=False, default="system")

    application: Mapped["Application"] = relationship(  # noqa: F821
        back_populates="events"
    )

    def __repr__(self) -> str:
        return f"<ApplicationEvent({self.event_type} app={self.application_id})>"
