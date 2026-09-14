"""Agent Ops: live per-agent state plus filterable run history.

Backs the multi-agent visualization — a node per named agent (Discovery, Eligibility,
Scoring, Application, Tracking), coloured by its most recent run's status, with a
filterable log underneath. Nothing here computes anything new: every row is a fact already
written by ``core.orchestration.recorder.record_agent_run`` at the point some agent actually
ran, so the graph can never show an agent as "active" that didn't really do anything.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.config.constants import DEFAULT_PAGE_SIZE
from app.models.agent_run import AgentRun
from app.models.enums import AgentName, AgentRunStatus
from app.schemas.agent_run import AgentNodeState, AgentRunItem, AgentRunListResponse

router = APIRouter()


@router.get("/", response_model=AgentRunListResponse, summary="Agent activity: live state + log")
async def list_agent_runs(
    user: CurrentUser,
    agent_name: AgentName | None = Query(default=None),
    status: AgentRunStatus | None = Query(default=None),
    linked_entity_type: str | None = Query(default=None),
    linked_entity_id: str | None = Query(default=None),
    since: datetime | None = Query(default=None, description="Only runs started at/after this"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=200),
    db: AsyncSession = Depends(get_tenant_db),
) -> AgentRunListResponse:
    """Filtered run history, most recent first, plus one node per named agent for the graph.

    The node list always has all five agents, even ones that have never run yet (``last_run``
    is ``None``) — the graph shows the full roster, not just whichever agents happen to have
    history, so an agent that has genuinely never fired reads as "idle", not "missing".
    """
    query = select(AgentRun).where(AgentRun.user_id == user.id)
    if agent_name is not None:
        query = query.where(AgentRun.agent_name == agent_name)
    if status is not None:
        query = query.where(AgentRun.status == status)
    if linked_entity_type is not None:
        query = query.where(AgentRun.linked_entity_type == linked_entity_type)
    if linked_entity_id is not None:
        query = query.where(AgentRun.linked_entity_id == linked_entity_id)
    if since is not None:
        query = query.where(AgentRun.started_at >= since)

    all_matching = (await db.execute(query.order_by(AgentRun.started_at.desc()))).scalars().all()
    total = len(all_matching)
    page_rows = all_matching[(page - 1) * page_size : (page - 1) * page_size + page_size]

    latest_by_agent: dict[AgentName, AgentRun] = {}
    all_rows = (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.user_id == user.id)
            .order_by(AgentRun.started_at.desc())
        )
    ).scalars()
    for row in all_rows:
        latest_by_agent.setdefault(row.agent_name, row)

    nodes = [
        AgentNodeState(
            agent_name=name,
            status=latest_by_agent[name].status if name in latest_by_agent else None,
            last_run=(
                AgentRunItem.model_validate(latest_by_agent[name]) if name in latest_by_agent
                else None
            ),
        )
        for name in AgentName
    ]

    return AgentRunListResponse(
        items=[AgentRunItem.model_validate(r) for r in page_rows],
        total=total,
        nodes=nodes,
    )
