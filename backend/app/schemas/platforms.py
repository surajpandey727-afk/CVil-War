"""Wire format for platform management.

One shape, assembled from the source registry and the user's stored sessions, so the Sources
screen and the Settings platform section cannot disagree about what the product supports or
what is connected. Two screens maintaining their own lists is how "Sources says Reed is
connected, Settings says it is not" happens.

Nothing here carries a credential. ``account`` is a masked label; the encrypted cookies live
in ``user_credentials`` and are never read on this path.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlatformAction(BaseModel):
    """An action the UI may offer for this platform, and whether it is available now.

    ``available`` is decided server-side because the frontend cannot know whether a session
    import is meaningful for a keyless public API. A disabled button with a reason beats a
    button that does nothing.
    """

    key: str
    label: str
    available: bool
    #: Why it is unavailable. Empty when it is.
    reason: str = ""


class PlatformStatus(BaseModel):
    """One source, its capabilities, and this user's connection to it."""

    key: str
    label: str
    tier: str
    #: Registry health: live / degraded / auth_required / not_implemented / blocked …
    health: str
    #: False when the source is catalogued but no adapter can serve it.
    implemented: bool
    #: True when the source cannot run without the operator supplying something.
    needs_credential: bool = False
    #: What this adapter can do — search, application_url, apply, and so on.
    capabilities: list[str] = Field(default_factory=list)

    #: Whether the operator has this source switched on for discovery.
    enabled: bool = False

    # -- Connection, for platforms that need a login -------------------------------------
    #: True only when a session exists AND is in a usable state.
    connected: bool = False
    #: Session lifecycle: session_active, session_expired, mfa_required, not_connected …
    connection_state: str = "not_connected"
    #: Masked, e.g. ``sur***@example.com``. Never a full address, never a credential.
    account: str | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    #: Why the connection needs attention, shown verbatim.
    detail: str | None = None

    #: Last time this source returned results, and what went wrong if it did not. Both are
    #: ``None`` when the source has never been exercised — different from "it failed".
    last_error: str | None = None

    actions: list[PlatformAction] = Field(default_factory=list)


class PlatformsResponse(BaseModel):
    """Every source the product knows about, with this user's state attached."""

    platforms: list[PlatformStatus] = Field(default_factory=list)
    total: int = 0
    #: Sources with a working adapter — the number that actually matters for discovery.
    usable: int = 0
    connected: int = 0
