"""Communications: Apollo outbound tracking and Gmail inbound reply detection, one feed.

``router`` carries every authenticated endpoint. ``public_router`` carries exactly one route —
the Gmail OAuth callback — because it is hit by a raw browser redirect from Google that
carries no Authorization header this app's normal auth dependency could read; the operator is
instead identified from the signed ``state`` value threaded through the redirect (see
``core.security.create_oauth_state``). Both are mounted at the same ``/communications`` prefix
in ``api.v1.router``, only one of them behind the router-level auth guard.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db, get_tenant_db
from app.config.constants import DEFAULT_PAGE_SIZE
from app.config.settings import get_settings
from app.core.exceptions import AuthError, RecordNotFoundError
from app.core.ratelimit import rate_limit
from app.core.security import decode_token
from app.models.application import Application
from app.models.communication_event import CommunicationEvent
from app.models.enums import ApplicationEventType
from app.schemas.communications import (
    ApolloStatus,
    CommunicationEventItem,
    CommunicationEventListResponse,
    GmailStatus,
    InboxSyncResponse,
    LinkApplicationRequest,
)
from app.services import gmail_auth
from app.services import inbox_sync as inbox_sync_service
from app.services.timeline import record_event

logger = structlog.get_logger(__name__)
router = APIRouter()
public_router = APIRouter()

# A sync makes real Gmail API calls (a message-list plus one fetch per message).
_COSTLY = Depends(rate_limit(10, 60))

_CLASSIFICATION_EVENT_TYPE: dict[str, ApplicationEventType] = {
    "rejection": ApplicationEventType.EMAIL_REJECTION_DETECTED,
    "interview_invite": ApplicationEventType.EMAIL_INTERVIEW_INVITE_DETECTED,
    "reply": ApplicationEventType.EMAIL_REPLY_RECEIVED,
}


@router.get("/gmail/status", response_model=GmailStatus, summary="Gmail connection state")
async def gmail_status(user: CurrentUser, db: AsyncSession = Depends(get_tenant_db)) -> GmailStatus:
    configured = gmail_auth.is_configured()
    connected = await gmail_auth.is_connected(db, user.id) if configured else False
    return GmailStatus(
        configured=configured,
        connected=connected,
        authorize_url=gmail_auth.authorize_url(user.id) if configured and not connected else None,
    )


@router.delete("/gmail", status_code=204, summary="Disconnect Gmail")
async def gmail_disconnect(user: CurrentUser, db: AsyncSession = Depends(get_tenant_db)) -> None:
    await gmail_auth.disconnect(db, user.id)


@router.get("/apollo/status", response_model=ApolloStatus, summary="Apollo configuration state")
async def apollo_status() -> ApolloStatus:
    return ApolloStatus(configured=bool(get_settings().apollo_api_key.get_secret_value()))


@router.post(
    "/inbox-sync",
    response_model=InboxSyncResponse,
    dependencies=[_COSTLY],
    summary="Pull recent Gmail messages, match and classify replies",
)
async def inbox_sync(
    user: CurrentUser, db: AsyncSession = Depends(get_tenant_db)
) -> InboxSyncResponse:
    """Run one sync cycle now, rather than waiting for the scheduled one.

    Raises a clear 400 when Gmail is not configured or not yet connected — the operator
    needs "go connect Gmail", not a generic 500.
    """
    try:
        result = await inbox_sync_service.sync_inbox(db, user.id)
    except (gmail_auth.GmailNotConfiguredError, gmail_auth.GmailNotConnectedError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InboxSyncResponse(
        fetched=result.fetched, already_seen=result.already_seen,
        matched_to_application=result.matched_to_application, unmatched=result.unmatched,
        errors=result.errors,
    )


@router.get(
    "/", response_model=CommunicationEventListResponse, summary="The communications feed"
)
async def list_communications(
    user: CurrentUser,
    unmatched_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_db),
) -> CommunicationEventListResponse:
    """Every captured communication, most recent first — unmatched ones are what need the
    operator's attention; matched ones already live on their application's own timeline too,
    and are included here so the feed reads as one complete inbox rather than a reject pile."""
    query = select(CommunicationEvent).where(CommunicationEvent.user_id == user.id)
    if unmatched_only:
        query = query.where(CommunicationEvent.application_id.is_(None))
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            query.order_by(CommunicationEvent.occurred_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    unmatched = (
        await db.execute(
            select(func.count()).select_from(CommunicationEvent).where(
                CommunicationEvent.user_id == user.id, CommunicationEvent.application_id.is_(None),
            )
        )
    ).scalar_one()
    return CommunicationEventListResponse(
        items=[CommunicationEventItem.model_validate(r) for r in rows],
        total=total, unmatched=unmatched,
    )


@router.post(
    "/{event_id}/link-application",
    response_model=CommunicationEventItem,
    summary="Manually attribute an unmatched communication to an application",
)
async def link_application(
    event_id: str,
    data: LinkApplicationRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> CommunicationEventItem:
    """The operator's own confirmation, for the cases the automatic matcher declined to
    guess at (ambiguous sender, more than one application at the same employer). Writes the
    same timeline entry a confident automatic match would have — linking late must not leave
    the application's own history looking like nothing happened.

    Both lookups are explicitly scoped by ``user_id`` — ``event_id``/``application_id`` are
    attacker-reachable path/body input, and ``Session.get()`` does NOT go through the ORM
    tenant filter (confirmed: it is a column/identity-map load, which the filter deliberately
    skips), so a plain ``db.get()`` here would let one operator read or write another's row.
    """
    event = (
        await db.execute(
            select(CommunicationEvent).where(
                CommunicationEvent.id == event_id, CommunicationEvent.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if event is None:
        raise RecordNotFoundError("Communication event not found")
    app = (
        await db.execute(
            select(Application).where(
                Application.id == data.application_id, Application.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if app is None:
        raise RecordNotFoundError("Application not found")

    event.application_id = app.id
    event.matched_confidence = 1.0
    event_type = _CLASSIFICATION_EVENT_TYPE.get(
        event.classified_as, ApplicationEventType.EMAIL_REPLY_RECEIVED
    )
    await record_event(
        db, app, event_type, f"Email reply linked: {event.subject or '(no subject)'}",
        detail=event.snippet, payload={"sender": event.sender, "linked_manually": True},
        occurred_at=event.occurred_at,
    )
    await db.commit()
    await db.refresh(event)
    return CommunicationEventItem.model_validate(event)


@public_router.get("/gmail/callback", summary="Gmail OAuth redirect target (public)")
async def gmail_callback(
    code: str, state: str, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    """Google redirects the operator's browser here after they grant (or refuse) access.

    Not behind the normal auth dependency — see the module docstring. ``get_db`` (unscoped)
    is used rather than ``get_tenant_db`` because there is no ambient tenant context on a
    request with no Authorization header; the user id instead comes from ``state``.
    """
    frontend = get_settings().frontend_url.rstrip("/")
    try:
        payload = decode_token(state, expected_type="oauth_state")
    except AuthError:
        return RedirectResponse(f"{frontend}/communications?gmail_error=invalid_state")

    try:
        await gmail_auth.exchange_code(db, payload["sub"], code)
    except Exception as exc:
        logger.warning("gmail.callback_exchange_failed", error=str(exc))
        return RedirectResponse(f"{frontend}/communications?gmail_error=exchange_failed")

    return RedirectResponse(f"{frontend}/communications?gmail_connected=1")
