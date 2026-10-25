"""Platform session routes: import / list / disconnect a job-platform login for the apply agent.

The apply worker cannot log a user into LinkedIn/Indeed/etc. unattended; instead the user's
captured browser ``storage_state`` is imported here (encrypted at rest) and later loaded into the
browser context by ``run_apply``. Cookies are never returned by any endpoint.
"""

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.config.settings import get_settings
from app.core.automation.connect import MANAGER, ConnectAttempt, target_for
from app.core.exceptions import RecordNotFoundError
from app.models.enums import SessionState
from app.models.platform_session import PlatformSession
from app.schemas.platform_session import (
    ConnectAttemptResponse,
    ConnectStart,
    PlatformSessionImport,
    PlatformSessionResponse,
)
from app.services import platform_session as service


def _attempt_response(attempt: ConnectAttempt) -> ConnectAttemptResponse:
    """Project an in-flight capture to its public view. Carries no cookies, ever."""
    return ConnectAttemptResponse(
        id=attempt.id,
        platform=attempt.platform,
        state=attempt.state.value,
        done=attempt.state.terminal,
        instructions=attempt.instructions,
        detail=attempt.detail,
        seconds_remaining=attempt.seconds_remaining,
    )


#: How a queued request's row state reads as an attempt state (see platform_session.py).
_ROW_TO_ATTEMPT = {
    SessionState.INTERACTIVE_AVAILABLE: "opening",
    SessionState.HUMAN_VERIFICATION_REQUIRED: "awaiting_login",
    SessionState.SESSION_ACTIVE: "connected",
    SessionState.SESSION_EXPIRING: "connected",
    SessionState.NOT_CONNECTED: "cancelled",
}


def _queued() -> bool:
    """Whether sign-ins run on the automation host rather than in this process.

    Tied to the apply dispatch on purpose: the machine that applies is the one that needs the
    session, and in production (Vercel, no browser) that is the DB-queue worker.
    """
    return get_settings().apply_dispatch == "db_queue"


def _row_response(row: PlatformSession) -> ConnectAttemptResponse:
    """Project a queued request row to the same shape the in-process attempt uses."""
    state = _ROW_TO_ATTEMPT.get(row.state, "failed")
    # A failed reconnect leaves a still-valid session active; the detail says what happened.
    if state == "connected" and row.state_detail:
        state = "cancelled" if row.state_detail.startswith("Cancel") else "failed"
    target = target_for(row.platform)
    return ConnectAttemptResponse(
        id=row.id,
        platform=row.platform,
        state=state,
        done=row.state not in service.CONNECT_PENDING,
        instructions=target.instructions if target else "",
        detail=row.state_detail or "",
        seconds_remaining=0,
    )


logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/",
    response_model=PlatformSessionResponse,
    status_code=201,
    summary="Import a platform session",
)
async def import_session(
    data: PlatformSessionImport,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PlatformSessionResponse:
    """Persist an encrypted browser session so the apply agent can reuse the login."""
    row = await service.import_session(
        db, user.id, data.platform, data.storage_state, expires_at=data.expires_at
    )
    return service.to_response(row)


@router.post(
    "/connect",
    response_model=ConnectAttemptResponse,
    status_code=202,
    summary="Open a login window so the operator can sign in themselves",
)
async def start_connect(
    data: ConnectStart,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConnectAttemptResponse:
    """Begin an interactive login capture.

    This is the answer to "how can the agent apply on my behalf without my credentials?" — it
    never has them. A visible browser opens on the platform's own login page, the operator
    signs in there (including any verification step, which they answer themselves), and only
    the resulting session is kept, encrypted. No password is requested, transmitted or stored,
    and no anti-bot measure is circumvented: a real person really does sign in.

    Returns immediately with an attempt to poll — a sign-in takes as long as it takes.
    """
    if _queued():
        return _row_response(await service.request_connect(db, user.id, data.platform))
    attempt = MANAGER.start(user.id, data.platform)
    return _attempt_response(attempt)


@router.get(
    "/connect/{attempt_id}",
    response_model=ConnectAttemptResponse,
    summary="Progress of a login capture",
)
async def connect_status(
    attempt_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConnectAttemptResponse:
    """Poll a capture. 404 once it has been pruned or if it belongs to another account."""
    if _queued():
        row = await service.get_connect_request(db, user.id, attempt_id)
        if row is None:
            raise RecordNotFoundError("No such connection attempt")
        return _row_response(row)
    attempt = MANAGER.get(attempt_id, user.id)
    if attempt is None:
        raise RecordNotFoundError("No such connection attempt")
    return _attempt_response(attempt)


@router.delete(
    "/connect/{attempt_id}",
    response_model=ConnectAttemptResponse,
    summary="Cancel a login capture and close its window",
)
async def cancel_connect(
    attempt_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConnectAttemptResponse:
    """Abandon a capture. The browser window closes and nothing is stored."""
    if _queued():
        row = await service.get_connect_request(db, user.id, attempt_id)
        if row is None:
            raise RecordNotFoundError("No such connection attempt")
        if row.state in service.CONNECT_PENDING:
            # The host sees the row leave the pending states and closes its window.
            await service.settle_connect(
                db, row, state=SessionState.NOT_CONNECTED, detail="Cancelled."
            )
        return _row_response(row)
    attempt = MANAGER.get(attempt_id, user.id)
    if attempt is None:
        raise RecordNotFoundError("No such connection attempt")
    MANAGER.cancel(attempt_id, user.id)
    return _attempt_response(attempt)


@router.get(
    "/", response_model=list[PlatformSessionResponse], summary="List connected platform sessions"
)
async def list_sessions(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[PlatformSessionResponse]:
    """List the current user's connected platform sessions (metadata only, no cookies)."""
    rows = await service.list_sessions(db, user.id)
    return [service.to_response(r) for r in rows]


@router.delete("/{platform}", status_code=204, summary="Disconnect a platform session")
async def delete_session(
    platform: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a stored platform session and its cookies. 404 if none was connected."""
    removed = await service.delete_session(db, user.id, platform.strip().lower())
    if not removed:
        raise RecordNotFoundError("No stored session for that platform")
