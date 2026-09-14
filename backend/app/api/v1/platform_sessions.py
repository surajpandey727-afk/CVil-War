"""Platform session routes: import / list / disconnect a job-platform login for the apply agent.

The apply worker cannot log a user into LinkedIn/Indeed/etc. unattended; instead the user's
captured browser ``storage_state`` is imported here (encrypted at rest) and later loaded into the
browser context by ``run_apply``. Cookies are never returned by any endpoint.
"""

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.core.automation.connect import MANAGER, ConnectAttempt
from app.core.exceptions import RecordNotFoundError
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
) -> ConnectAttemptResponse:
    """Begin an interactive login capture.

    This is the answer to "how can the agent apply on my behalf without my credentials?" — it
    never has them. A visible browser opens on the platform's own login page, the operator
    signs in there (including any verification step, which they answer themselves), and only
    the resulting session is kept, encrypted. No password is requested, transmitted or stored,
    and no anti-bot measure is circumvented: a real person really does sign in.

    Returns immediately with an attempt to poll — a sign-in takes as long as it takes.
    """
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
) -> ConnectAttemptResponse:
    """Poll a capture. 404 once it has been pruned or if it belongs to another account."""
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
) -> ConnectAttemptResponse:
    """Abandon a capture. The browser window closes and nothing is stored."""
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
