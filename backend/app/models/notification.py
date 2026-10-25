"""In-app notifications: new jobs, best matches, application outcomes, things that need you.

One row per thing worth telling the user about. ``kind`` and ``severity`` are plain strings,
not database enums, so the table migrates identically on SQLite and PostgreSQL (database enum
types are what broke earlier migrations on a fresh Postgres) and new kinds need no migration.
``dedup_key`` makes emitting idempotent: the same event raised twice (a retried worker job, a
re-run search) produces one notification, enforced by a unique index rather than a read-then-
write check.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Something the user should know about, with where to go to act on it."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_notification_dedup"),
        # The feed and the unread badge both read one user's newest rows.
        Index("ix_notification_user_created", "user_id", "created_at"),
        Index("ix_notification_user_unread", "user_id", "read_at"),
    )

    #: new_jobs | best_match | application_submitted | application_failed | action_required
    #: | application_held | interview | recruiter_reply | rejection | system
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    #: info | success | warning | critical — drives the icon and colour, nothing else.
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: In-app path to open, e.g. "/applications/<id>" or "/jobs?focus=<id>".
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: When (and whether) the email copy went out; NULL means not emailed.
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Notification({self.kind} user={self.user_id} read={self.read_at is not None})>"
