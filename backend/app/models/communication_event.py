"""An inbound (Gmail) or outbound (Apollo) communication, before it is known which
application it belongs to.

A high-confidence match writes straight onto the matched application's own timeline (see
``services.timeline.record_event``) — that is the single source of truth for "what happened on
this application" and this table must not become a second one. This table exists for the
events that arrive *without* an application obviously attached: a reply from a company you
applied to more than once, a recruiter reaching out cold, a rejection whose sender name and
the job posting's own name don't match cleanly. Rather than silently dropping (or wrongly
guessing) which application these belong to, they land here for the operator to confirm.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class CommunicationEvent(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One inbound or outbound communication captured by an integration sync."""

    __tablename__ = "communication_events"
    __table_args__ = (
        # The same Gmail message or Apollo activity must never be recorded twice just because
        # a sync ran again — inbox-sync has no way to know which messages it already saw
        # except by checking this.
        UniqueConstraint("user_id", "source", "external_id", name="uq_communication_event"),
        Index("ix_communication_event_user_occurred", "user_id", "occurred_at"),
    )

    #: "gmail" | "apollo" — which integration produced this row.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The source system's own id for this item (Gmail message id, Apollo activity id).
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    application_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    sender: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: 0-1. How sure the matcher was about ``application_id`` (0 when it is still None).
    matched_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: "rejection" | "interview_invite" | "reply" | "" — best-effort classification of an
    #: inbound reply's content. Blank for outbound (Apollo) events, which have no reply to read.
    classified_as: Mapped[str] = mapped_column(String(30), nullable=False, default="")
