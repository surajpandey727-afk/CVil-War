"""Per-user platform browser-session metadata (assisted-login sessions, D7)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import SessionState


class PlatformSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks a user's stored browser session on a job platform.

    The encrypted browser ``storage_state`` itself lives in ``user_credentials``
    (kind=``platform_cookies``); this row holds verification/expiry metadata and the
    fingerprint used, so the worker can decide whether to reuse or prompt re-auth.
    Explicit ``user_id`` (not ``TenantMixin``): read from the worker outside tenant scope.
    """

    __tablename__ = "platform_sessions"
    __table_args__ = (UniqueConstraint("user_id", "platform", name="uq_platform_session"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fingerprint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # -- Granular lifecycle (Job OS §6/§7) ----------------------------------------------
    #
    # Collapsing these into a generic FAILED is what produced dead ends: an expired session
    # needs a reconnect, MFA needs a hand-off, and a server block means a different access
    # mechanism entirely. Three different user actions, so three different states.
    state: Mapped[SessionState] = mapped_column(
        pg_enum(SessionState, "session_state"),
        nullable=False,
        default=SessionState.NOT_CONNECTED,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Why the session needs attention, shown to the user verbatim.
    state_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: Count of applications currently relying on this session, for the connection centre.
    applications_tracked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
