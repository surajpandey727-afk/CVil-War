"""Per-user settings model (one row per user; ``user_id`` is the primary key)."""

from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserSettings(TimestampMixin, Base):
    """A user's preferences and configuration.

    One row per user — ``user_id`` is both the PK and the FK to ``users``. Queried by
    explicit ``user_id`` (not via the tenant filter, since it is PK-scoped).
    """

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Application behavior
    apply_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="review")
    max_parallel: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    min_ats_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)

    # LLM preferences
    preferred_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="openai")

    # Platform config
    platforms_enabled: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: ["linkedin", "indeed", "glassdoor"],
    )

    # Candidate profile
    candidate_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # -- Discovery and automation preferences ------------------------------------------
    #
    # Both are JSON blobs rather than columns because their shape is owned by the UI and
    # changes with it: promoting each rule and threshold to a column would mean a migration
    # every time the automation screen grows a control. They are validated on the way in by
    # ``AutomationSettingsSchema`` / ``RoleTargetSchema``, so the looseness stops at the API
    # boundary and never reaches the worker.

    #: Role titles the operator is targeting, with fit and family. See ``RoleTargetSchema``.
    role_targets: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    #: Auto-apply rules: thresholds, résumé selection, cover letters, failure handling,
    #: run window. See ``AutomationSettingsSchema``.
    automation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UserSettings(user_id={self.user_id}, apply_mode='{self.apply_mode}', "
            f"provider='{self.preferred_provider}')>"
        )
