"""Application timeline and next-action maintenance.

Two responsibilities, kept together because they always happen as a pair: something changes
about an application, so the timeline records *what happened* and the action engine
recomputes *what to do about it*.

Callers should use :func:`record_event`, never construct ``ApplicationEvent`` directly — the
recompute is the whole point, and a hand-written insert silently skips it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actions.engine import apply_verdict, compute_action
from app.models.application import Application
from app.models.application_event import ApplicationEvent
from app.models.enums import ApplicationEventType

logger = structlog.get_logger(__name__)


async def record_event(
    db: AsyncSession,
    app: Application,
    event_type: ApplicationEventType,
    summary: str,
    *,
    detail: str | None = None,
    payload: dict | None = None,
    actor: str = "system",
    occurred_at: datetime | None = None,
    recompute: bool = True,
) -> ApplicationEvent:
    """Append a timeline entry and refresh the application's next action.

    ``occurred_at`` defaults to now but is settable so imported history keeps its real dates
    rather than collapsing onto the import time.

    The caller commits. Batching several events into one transaction is normal — a submission
    writes both APPLICATION_SUBMITTED and STATUS_CHANGED — and committing here would make
    each of those separately durable for no benefit.
    """
    event = ApplicationEvent(
        user_id=app.user_id,
        application_id=app.id,
        event_type=event_type,
        occurred_at=occurred_at or datetime.now(UTC),
        summary=summary[:300],
        detail=detail,
        payload=payload,
        actor=actor,
    )
    db.add(event)
    app.last_activity_at = event.occurred_at

    if recompute:
        apply_verdict(app, compute_action(app))

    logger.info(
        "application.event",
        application_id=app.id,
        # NOT `event=`: structlog names its first positional argument `event`, so that kwarg
        # collides with the message itself and raises TypeError at call time.
        event_type=event_type.value,
        actor=actor,
        next_action=app.next_action.value,
    )
    return event


async def refresh_actions(db: AsyncSession, user_id: str) -> int:
    """Recompute next actions for every one of a user's applications.

    Run on a schedule and before the dashboard loads, because most transitions are driven by
    the clock rather than by an event: an assessment becomes urgent, a submission goes quiet,
    a paused application goes stale. Nothing writes an event when time passes, so without a
    sweep the queue would only ever be as fresh as the last user action.

    Only genuine changes write a timeline entry — see ``apply_verdict``'s change flag.
    """
    applications = (
        (await db.execute(select(Application).where(Application.user_id == user_id)))
        .scalars()
        .all()
    )
    changed = 0
    for app in applications:
        verdict = compute_action(app)
        if apply_verdict(app, verdict):
            changed += 1
            await record_event(
                db,
                app,
                ApplicationEventType.USER_ACTION_REQUIRED
                if verdict.is_actionable
                else ApplicationEventType.STATUS_CHANGED,
                verdict.reason,
                payload={"action": verdict.action.value, "priority": verdict.priority.value},
                actor="system",
                recompute=False,  # already applied above; avoid recomputing twice
            )
    if changed:
        await db.commit()
    return changed
