"""System status for the in-app connection widget.

One user-scoped call that answers "what is connected, what is pending, and what do I click to
fix it" — the services the app actually depends on (database, the LLM gateway, Gmail, the job
boards) and this user's automation mode. It reuses the same signals as ``/health`` but adds the
per-user connection state (Gmail connected, job boards connected) that a readiness probe cannot
carry, so the frontend can render one honest status surface instead of guessing from a websocket
that serverless can never hold open.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.services import gmail_auth

router = APIRouter()


class ServiceState(BaseModel):
    """One dependency's state, plus where the user goes to act on it."""

    key: str
    label: str
    status: str  # "connected" | "pending" | "unavailable" | "not_configured"
    detail: str = ""
    #: In-app route that lets the user fix a non-connected service, when one exists.
    action_path: str = ""
    action_label: str = ""


class SystemStatusResponse(BaseModel):
    services: list[ServiceState]
    #: True when every service the app needs to function is connected.
    all_ok: bool
    #: Convenience summary for the pill label, e.g. "2 need attention".
    attention: int


async def _gmail_state(db: AsyncSession, user_id: str) -> ServiceState:
    if not gmail_auth.is_configured():
        return ServiceState(
            key="gmail", label="Gmail notifications", status="not_configured",
            detail="No Google OAuth client is set up on this deployment.",
            action_path="/communications", action_label="Set up",
        )
    connected = await gmail_auth.is_connected(db, user_id)
    return ServiceState(
        key="gmail", label="Gmail notifications",
        status="connected" if connected else "pending",
        detail="Connected — you'll be emailed when applications go out."
        if connected else "Configured but not connected. Connect to get notified.",
        action_path="" if connected else "/communications",
        action_label="" if connected else "Connect",
    )


async def _llm_state() -> ServiceState:
    from app.core.llm.discovery import discover as discover_llm_gateway

    try:
        catalogue = await asyncio.wait_for(discover_llm_gateway(), timeout=2.5)
        reachable, error = catalogue.reachable, catalogue.error
    except Exception as exc:  # timeout or discovery failure — report, never raise
        reachable, error = False, str(exc)
    return ServiceState(
        key="llm", label="AI model gateway",
        status="connected" if reachable else "unavailable",
        detail="Reachable — résumé tailoring and AI features can run."
        if reachable else f"Not reachable: {error or 'gateway down'}.",
    )


async def _platforms_state(db: AsyncSession, user_id: str) -> ServiceState:
    from app.services import platforms as platform_service

    try:
        resp = await platform_service.list_platforms(db, user_id)
        connected = sum(1 for p in resp.items if p.connected)
    except Exception:
        connected = 0
    return ServiceState(
        key="job_boards", label="Job boards (apply)",
        status="connected" if connected else "pending",
        detail=f"{connected} connected — the agent can submit on these."
        if connected
        else "No job board connected. The agent can't submit until you sign in to one.",
        action_path="" if connected else "/settings",
        action_label="" if connected else "Connect",
    )


async def _agent_state(db: AsyncSession, user_id: str) -> ServiceState:
    from sqlalchemy import select

    from app.models.user_settings import UserSettings

    row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    automation = (row.automation if row else {}) or {}
    mode = str(automation.get("mode") or automation.get("apply_mode") or "review")
    autonomous = mode == "autonomous"
    return ServiceState(
        key="ai_agent", label="AI apply agent",
        status="connected" if autonomous else "pending",
        detail="Autonomous — applies on its own within your rules."
        if autonomous else f"Review mode — you approve each application ({mode}).",
        action_path="/settings", action_label="Change",
    )


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    summary="Connection status of every dependency",
)
async def system_status(
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> SystemStatusResponse:
    """Every dependency's connection state for the status widget. Never raises on a dead
    dependency — a down service is a reported ``unavailable``/``pending``, not a 500."""
    database = ServiceState(
        key="database", label="Database", status="connected",
        detail="Connected.",
    )
    # The LLM gateway check is a network call and the slow part; run it alongside the DB calls.
    # The DB calls themselves must be sequential — one AsyncSession is not safe for concurrent use.
    llm_task = asyncio.create_task(_llm_state())
    gmail = await _gmail_state(db, user.id)
    boards = await _platforms_state(db, user.id)
    agent = await _agent_state(db, user.id)
    llm = await llm_task
    services = [agent, llm, gmail, boards, database]
    attention = sum(1 for s in services if s.status in ("pending", "unavailable", "not_configured"))
    return SystemStatusResponse(services=services, all_ok=attention == 0, attention=attention)
