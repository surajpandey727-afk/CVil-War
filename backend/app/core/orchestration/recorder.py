"""Shared instrumentation every agent uses: write an ``AgentRun`` row, publish a live
WebSocket event on every state change, and never let observability break the agent itself.

The WS event mirrors ``core.automation.intervention.needs_intervention_event``'s own
reasoning for why this lives outside the main persistence path: the operator needs to know
the moment something happens, not only when they next reload the page.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.enums import AgentName, AgentRunStatus

logger = structlog.get_logger(__name__)


def agent_state_event(run: AgentRun) -> dict[str, Any]:
    """The WS event shape the Agent Ops view (and, eventually, a future notification) reads."""
    return {
        "type": "agent_state_changed",
        "payload": {
            "agent_run_id": run.id,
            "agent_name": run.agent_name.value,
            "status": run.status.value,
            "input_summary": run.input_summary,
            "output_summary": run.output_summary,
            "error": run.error,
            "linked_entity_type": run.linked_entity_type,
            "linked_entity_id": run.linked_entity_id,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        },
    }


async def _publish(redis: Any | None, user_id: str, run: AgentRun) -> None:
    if redis is None:
        return
    try:
        from app.api.websocket.bus import publish_progress

        await publish_progress(redis, user_id, agent_state_event(run))
    except Exception as exc:  # a dead WS bus must never fail the agent it is reporting on
        logger.debug("orchestration.publish_failed", agent=run.agent_name, error=str(exc))


@asynccontextmanager
async def record_agent_run(
    db: AsyncSession,
    user_id: str,
    agent_name: AgentName,
    *,
    input_summary: str = "",
    linked_entity_type: str | None = None,
    linked_entity_id: str | None = None,
    redis: Any | None = None,
) -> AsyncIterator[AgentRun]:
    """Wrap one agent invocation: write RUNNING, yield the row so the caller can set
    ``output_summary``, then write DONE (or ERROR if the block raised) — always, via
    ``finally``, so a crashed agent still leaves a closed, honest record rather than one
    stuck at RUNNING forever.

    Usage::

        async with record_agent_run(db, user_id, AgentName.ELIGIBILITY, input_summary=...) as run:
            confidence, evidence = classify(job.company, job.description)
            run.output_summary = f"{confidence.value}: {evidence or 'no evidence'}"
    """
    run = AgentRun(
        user_id=user_id,
        agent_name=agent_name,
        status=AgentRunStatus.RUNNING,
        started_at=datetime.now(UTC),
        input_summary=input_summary[:300] or None,
        linked_entity_type=linked_entity_type,
        linked_entity_id=linked_entity_id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await _publish(redis, user_id, run)

    try:
        yield run
    except BaseException as exc:
        # BaseException, not Exception: a job_timeout cancellation (asyncio.CancelledError)
        # must close this row too, or a timed-out agent is left stuck at RUNNING forever.
        if run.status == AgentRunStatus.RUNNING:
            run.status = AgentRunStatus.ERROR
        run.error = str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        await db.commit()
        await _publish(redis, user_id, run)
        raise
    else:
        # A caller may set a specific terminal status (e.g. NEEDS_REVIEW) on `run` before
        # returning normally; only default to DONE if it left the status untouched.
        if run.status == AgentRunStatus.RUNNING:
            run.status = AgentRunStatus.DONE
        run.finished_at = datetime.now(UTC)
        await db.commit()
        await _publish(redis, user_id, run)
