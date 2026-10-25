"""Assistant + AI Agents routes.

``/chat`` runs the Claude tool-use loop as the current user (every tool shares this request's
tenant-scoped session). Consequential tools only return a signed token; ``/confirm`` is the
one place they execute. ``/agents`` is the AI Agents roster.
"""

from __future__ import annotations

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_redis, get_tenant_db
from app.core.assistant.context import ToolContext
from app.core.assistant.loop import AssistantUnavailableError
from app.core.ratelimit import rate_limit
from app.db.arq import get_arq_pool
from app.schemas.assistant import (
    AgentRosterResponse,
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    ConfirmResponse,
    PrepareRequest,
    PrepareResponse,
)
from app.services import assistant as service

router = APIRouter()

# Paid LLM calls (and the actions they unlock): cap per client like the other LLM routes.
_COSTLY = Depends(rate_limit(30, 60))


def _ctx(
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
    redis: Redis | None = Depends(get_redis),
    pool: ArqRedis | None = Depends(get_arq_pool),
) -> ToolContext:
    return ToolContext(db=db, user_id=user.id, redis=redis, pool=pool)


@router.post(
    "/chat", response_model=ChatResponse, dependencies=[_COSTLY], summary="Talk to the Assistant"
)
async def chat(data: ChatRequest, ctx: ToolContext = Depends(_ctx)) -> ChatResponse:
    """One assistant turn over a text-only history. Tools run as you; anything
    consequential comes back in ``pending`` for you to confirm."""
    try:
        return await service.chat(ctx, data.messages)
    except AssistantUnavailableError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post(
    "/confirm",
    response_model=ConfirmResponse,
    dependencies=[_COSTLY],
    summary="Confirm an action the Assistant proposed",
)
async def confirm(data: ConfirmRequest, ctx: ToolContext = Depends(_ctx)) -> ConfirmResponse:
    """Execute a signed, unexpired, unused pending action that belongs to you."""
    return await service.confirm(ctx, data.token)


@router.post(
    "/prepare",
    response_model=PrepareResponse,
    summary="Propose an agent action for confirmation (AI Agents page)",
)
async def prepare(data: PrepareRequest, ctx: ToolContext = Depends(_ctx)) -> PrepareResponse:
    return await service.prepare(ctx, data.action)


@router.get("/agents", response_model=AgentRosterResponse, summary="The AI Agents roster")
async def agents(ctx: ToolContext = Depends(_ctx)) -> AgentRosterResponse:
    """Every agent with its status, last run, counts and the actions it offers."""
    return await service.roster(ctx)
