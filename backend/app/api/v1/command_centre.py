"""Command centre: the action queue, application timelines, and the "needs attention" view.

This is the operational surface of the Job OS. It answers one question the rest of the API
does not: *what should I do next, and why?* Status endpoints report state; these report
consequences.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, get_tenant_db
from app.core.actions.engine import compute_action
from app.models.application import Application
from app.models.application_event import ApplicationEvent
from app.models.enums import ActionPriority, NextAction
from app.schemas.command_centre import (
    ActionItem,
    ActionQueueResponse,
    ApplicationTimelineResponse,
    CommandCentreSummary,
    TimelineEntry,
)
from app.services import timeline as timeline_service

logger = structlog.get_logger(__name__)
router = APIRouter()

#: Actions that are informational rather than something the user must do. Excluded from the
#: queue so it stays a to-do list — a queue padded with "in progress" items gets ignored.
_NON_ACTIONABLE = frozenset({NextAction.NONE, NextAction.WAIT})

_PRIORITY_RANK = {
    ActionPriority.HIGH: 0,
    ActionPriority.MEDIUM: 1,
    ActionPriority.LOW: 2,
    ActionPriority.NONE: 3,
}

#: Where each action should take the user. The queue is only useful if a click lands on the
#: exact thing that needs doing rather than a page they must then navigate from.
_ACTION_TARGET: dict[NextAction, str] = {
    NextAction.COMPLETE_ASSESSMENT: "assessment",
    NextAction.PREPARE_INTERVIEW: "interview",
    NextAction.RELOGIN: "connection",
    NextAction.COMPLETE_VERIFICATION: "connection",
    NextAction.RESUME_APPLICATION: "resume",
    NextAction.UPLOAD_CV: "documents",
    NextAction.UPLOAD_DOCUMENT: "documents",
    NextAction.REVIEW_APPLICATION: "review",
    NextAction.REVIEW_ANSWER: "review",
    NextAction.CONFIRM_APPLICATION: "review",
    NextAction.VERIFY_SUBMISSION: "verify",
    NextAction.FOLLOW_UP: "follow_up",
    NextAction.RESPOND_TO_RECRUITER: "messages",
    NextAction.SCHEDULE_INTERVIEW: "interview",
    NextAction.UPDATE_PROFILE: "profile",
}


async def _load(db: AsyncSession, user_id: str) -> list[Application]:
    result = await db.execute(
        select(Application)
        .where(Application.user_id == user_id)
        .options(selectinload(Application.job))
    )
    return list(result.scalars().all())


def _to_item(app: Application) -> ActionItem:
    job = app.job
    return ActionItem(
        application_id=app.id,
        job_id=app.job_id,
        title=job.title if job else "Unknown role",
        company=job.company if job else "",
        action=app.next_action,
        priority=app.next_action_priority,
        reason=app.next_action_reason or "",
        score=app.next_action_score,
        due_at=app.action_due_at,
        health=app.health,
        status=app.status,
        target=_ACTION_TARGET.get(app.next_action, "application"),
        application_url=app.application_url,
        portal=app.portal,
    )


@router.get("/queue", response_model=ActionQueueResponse, summary="Unified action queue")
async def action_queue(
    user: CurrentUser,
    refresh: bool = Query(default=True, description="Recompute before returning"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ActionQueueResponse:
    """Everything needing the user, most consequential first.

    Recomputes by default: most transitions are driven by the clock, not by an event — an
    assessment becomes urgent, a submission goes quiet — so a queue served straight from
    stored values would be stale exactly when it matters most.
    """
    if refresh:
        await timeline_service.refresh_actions(db, user.id)

    apps = await _load(db, user.id)
    items = [_to_item(a) for a in apps if a.next_action not in _NON_ACTIONABLE]
    items.sort(key=lambda i: (_PRIORITY_RANK[i.priority], -i.score))

    counts: dict[str, int] = {}
    for item in items:
        counts[item.priority.value] = counts.get(item.priority.value, 0) + 1

    return ActionQueueResponse(items=items, total=len(items), by_priority=counts)


@router.get("/summary", response_model=CommandCentreSummary, summary="Dashboard summary")
async def summary(
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> CommandCentreSummary:
    """Counts behind the dashboard's "needs attention" and "active" panels.

    Derived live rather than stored: a cached counter that drifts from the queue is worse
    than no counter, because the user stops believing both.
    """
    await timeline_service.refresh_actions(db, user.id)
    apps = await _load(db, user.id)
    now = datetime.now(UTC)

    by_status: dict[str, int] = {}
    by_health: dict[str, int] = {}
    for a in apps:
        by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
        by_health[a.health.value] = by_health.get(a.health.value, 0) + 1

    actionable = [a for a in apps if a.next_action not in _NON_ACTIONABLE]
    high = [a for a in actionable if a.next_action_priority is ActionPriority.HIGH]

    def _upcoming(field: str) -> int:
        return sum(
            1
            for a in apps
            if (when := getattr(a, field)) is not None
            and (when.replace(tzinfo=UTC) if when.tzinfo is None else when) >= now
        )

    return CommandCentreSummary(
        total_applications=len(apps),
        needs_attention=len(actionable),
        high_priority=len(high),
        by_status=by_status,
        by_health=by_health,
        upcoming_interviews=_upcoming("interview_at"),
        pending_assessments=_upcoming("assessment_due_at"),
        top_actions=[_to_item(a) for a in sorted(
            actionable, key=lambda a: -a.next_action_score
        )[:5]],
    )


@router.get(
    "/applications/{application_id}/timeline",
    response_model=ApplicationTimelineResponse,
    summary="Full application timeline",
)
async def application_timeline(
    application_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationTimelineResponse:
    """Chronological history of one application, oldest first."""
    result = await db.execute(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.occurred_at)
    )
    events = list(result.scalars().all())

    app = (
        await db.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    verdict = compute_action(app) if app is not None else None

    return ApplicationTimelineResponse(
        application_id=application_id,
        entries=[
            TimelineEntry(
                id=e.id,
                event_type=e.event_type,
                occurred_at=e.occurred_at,
                summary=e.summary,
                detail=e.detail,
                actor=e.actor,
                payload=e.payload,
            )
            for e in events
        ],
        total=len(events),
        current_action=verdict.action if verdict else NextAction.NONE,
        current_reason=verdict.reason if verdict else "",
    )
