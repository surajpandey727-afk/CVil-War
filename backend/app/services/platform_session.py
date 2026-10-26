"""Platform session service: import, list, and delete per-user browser sessions.

The encrypted ``storage_state`` lives in ``user_credentials`` (via :class:`CredentialStore`);
the ``platform_sessions`` row holds the cookie-free verification metadata the worker consults
before an apply run. Both are keyed by an explicit ``user_id`` (neither is a tenant entity).
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets.credential_store import CredentialStore
from app.models.enums import SessionState
from app.models.platform_session import PlatformSession
from app.schemas.platform_session import PlatformSessionResponse

logger = structlog.get_logger(__name__)


def _fingerprint(storage_state: dict[str, Any]) -> str:
    """A stable hash of the session, so a re-import can be recognised as the same login."""
    return hashlib.sha256(json.dumps(storage_state, sort_keys=True).encode()).hexdigest()


def to_response(row: PlatformSession) -> PlatformSessionResponse:
    """Project a stored session to its cookie-free public view."""
    return PlatformSessionResponse(
        platform=row.platform,
        connected=True,
        last_verified_at=row.last_verified_at,
        expires_at=row.expires_at,
    )


async def import_session(
    db: AsyncSession,
    user_id: str,
    platform: str,
    storage_state: dict[str, Any],
    *,
    expires_at: datetime | None = None,
) -> PlatformSession:
    """Encrypt+store the storage_state and upsert the platform-session metadata row."""
    await CredentialStore().save_session_cookies(db, user_id, platform, storage_state)

    now = datetime.now(UTC)
    fingerprint = _fingerprint(storage_state)
    row = (
        await db.execute(
            select(PlatformSession).where(
                PlatformSession.user_id == user_id, PlatformSession.platform == platform
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PlatformSession(
            user_id=user_id,
            platform=platform,
            last_verified_at=now,
            expires_at=expires_at,
            fingerprint_hash=fingerprint,
        )
        db.add(row)
    else:
        row.last_verified_at = now
        row.expires_at = expires_at
        row.fingerprint_hash = fingerprint
    # A stored session is a usable one. Without this a first connection stayed at the column
    # default (``not_connected``), so a successful sign-in never showed as connected.
    row.state = SessionState.SESSION_ACTIVE
    row.state_detail = None
    await db.commit()
    await db.refresh(row)
    logger.info("platform_session_imported", user_id=user_id, platform=platform)
    return row


async def list_sessions(db: AsyncSession, user_id: str) -> list[PlatformSession]:
    """Return the user's stored platform sessions (metadata only)."""
    result = await db.execute(
        select(PlatformSession)
        .where(PlatformSession.user_id == user_id)
        .order_by(PlatformSession.platform)
    )
    return list(result.scalars().all())


async def delete_session(db: AsyncSession, user_id: str, platform: str) -> bool:
    """Remove a platform's session (cookies + metadata). Returns True if anything was removed."""
    had_cookies = await CredentialStore().delete_session_cookies(db, user_id, platform)
    result = await db.execute(
        delete(PlatformSession).where(
            PlatformSession.user_id == user_id, PlatformSession.platform == platform
        )
    )
    await db.commit()
    removed = had_cookies or result.rowcount > 0
    if removed:
        logger.info("platform_session_deleted", user_id=user_id, platform=platform)
    return removed


# -- Queued sign-in (production) ------------------------------------------------------------
#
# The production API runs on Vercel, where there is no browser to open, and an in-memory
# attempt would not survive the next request landing on another instance. So in production a
# Connect click becomes a row the automation host (the DB-queue worker on the owner's PC)
# picks up: it opens the sign-in window on that desktop and stores the session. The row's
# ``state`` carries the progress, so no new table is needed:
#
#   interactive_available        -> requested, waiting for the automation host
#   human_verification_required  -> window open, the person is signing in
#   session_active               -> stored (import_session sets it)
#   auth_required / not_connected -> failed / cancelled, with the reason in ``state_detail``

CONNECT_PENDING = (SessionState.INTERACTIVE_AVAILABLE, SessionState.HUMAN_VERIFICATION_REQUIRED)

#: Shown while nothing has picked the request up yet.
WAITING_FOR_HOST = (
    "Waiting for the automation host on your PC to open the sign-in window. If nothing opens "
    "within a minute, start it: .\\scripts\\db-worker.ps1 -Start -ConnectOnly "
    "(see docs/LOCAL_SETUP.md)."
)


#: A pending request untouched for longer than a sign-in window can stay open belongs to a
#: host that died mid-capture; a new click starts over instead of waiting on it forever.
_PENDING_STALE_AFTER = timedelta(minutes=12)


def _stale(row: PlatformSession) -> bool:
    stamp = row.updated_at
    if stamp is None:
        return False
    if stamp.tzinfo is None:  # SQLite hands back naive UTC
        stamp = stamp.replace(tzinfo=UTC)
    return datetime.now(UTC) - stamp > _PENDING_STALE_AFTER


async def _row(db: AsyncSession, user_id: str, platform: str) -> PlatformSession | None:
    return (
        await db.execute(
            select(PlatformSession).where(
                PlatformSession.user_id == user_id, PlatformSession.platform == platform
            )
        )
    ).scalar_one_or_none()


async def request_connect(db: AsyncSession, user_id: str, platform: str) -> PlatformSession:
    """Record a sign-in request for the automation host. Idempotent while one is pending."""
    row = await _row(db, user_id, platform)
    if row is None:
        row = PlatformSession(user_id=user_id, platform=platform)
        db.add(row)
    elif row.state in CONNECT_PENDING and not _stale(row):
        return row
    row.state = SessionState.INTERACTIVE_AVAILABLE
    row.state_detail = WAITING_FOR_HOST
    await db.commit()
    await db.refresh(row)
    logger.info("platform_connect_requested", user_id=user_id, platform=platform)
    return row


async def get_connect_request(
    db: AsyncSession, user_id: str, row_id: str
) -> PlatformSession | None:
    """The request row, scoped to its owner so an id cannot be read across accounts."""
    row = await db.get(PlatformSession, row_id)
    if row is None or row.user_id != user_id:
        return None
    await expire_if_stranded(db, row)
    return row


#: Said when a sign-in request outlived any window that could still be open.
STRANDED = (
    "The sign-in window didn't finish - the automation host on your PC may have stopped or "
    "the window was closed. Click Connect to try again."
)


async def expire_if_stranded(db: AsyncSession, row: PlatformSession) -> bool:
    """End a sign-in request no host is still working on.

    A host that died after claiming a request left it "in progress" for good: the screen kept
    saying a window was open, and a session that worked before the reconnect showed as
    disconnected. Past the window's lifetime the request is settled; a still-valid earlier
    session goes back to active (see ``settle_connect``).
    """
    if row.state not in CONNECT_PENDING or not _stale(row):
        return False
    await settle_connect(db, row, state=SessionState.AUTH_REQUIRED, detail=STRANDED)
    return True


async def settle_connect(
    db: AsyncSession, row: PlatformSession, *, state: SessionState, detail: str
) -> None:
    """End a request that did not store a session.

    A reconnect that fails must not strand a session that still works: when the stored
    cookies have not expired, the row goes back to active and the failure is kept as detail.
    """
    still_valid = row.fingerprint_hash is not None and (
        row.expires_at is None or row.expires_at > datetime.now(UTC)
    )
    row.state = SessionState.SESSION_ACTIVE if still_valid else state
    row.state_detail = detail[:300]
    await db.commit()


async def pending_connects(db: AsyncSession, limit: int = 5) -> list[PlatformSession]:
    """Requests no host has started yet, oldest first. Unscoped: the worker serves everyone."""
    result = await db.execute(
        select(PlatformSession)
        .where(PlatformSession.state == SessionState.INTERACTIVE_AVAILABLE)
        .order_by(PlatformSession.updated_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())
