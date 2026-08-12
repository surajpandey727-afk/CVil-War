"""Persist LLM usage records to the database for per-user cost tracking.

``record_usage`` writes one ``LLMUsage`` row (the DB session is injected, so it is unit
testable). ``persist_usage_for_user`` is the production side-effect the ``LLMClient`` fires
after every call: it opens its OWN short-lived session (decoupled from the request
transaction) and never raises — usage accounting must never break an LLM call.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.client import LLMResponse
from app.models.enums import LLMPurpose
from app.models.llm_usage import LLMUsage

logger = structlog.get_logger(__name__)


def _coerce_purpose(purpose: str | LLMPurpose) -> LLMPurpose:
    """Map a free-form purpose label onto the LLMPurpose enum (GENERAL catch-all)."""
    if isinstance(purpose, LLMPurpose):
        return purpose
    try:
        return LLMPurpose(purpose)
    except ValueError:
        return LLMPurpose.GENERAL


async def record_usage(
    db: AsyncSession,
    response: LLMResponse,
    *,
    user_id: str,
    purpose: str | LLMPurpose = "general",
    trace_id: str | None = None,
    status: str = "success",
    error: str | None = None,
) -> LLMUsage:
    """Save one LLM call record (caller supplies the session and the owning user_id)."""
    record = LLMUsage(
        user_id=user_id,
        provider=response.provider,
        model=response.model,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        total_tokens=response.total_tokens,
        cost_usd=response.cost_usd,
        latency_ms=int(response.latency_ms),
        purpose=_coerce_purpose(purpose),
        trace_id=trace_id,
        status=status,
        error=error[:500] if error else None,
    )
    db.add(record)
    await db.commit()
    logger.debug(
        "llm_usage_recorded",
        user_id=user_id,
        provider=response.provider,
        model=response.model,
        tokens=response.total_tokens,
        cost=round(response.cost_usd, 6),
        purpose=str(record.purpose),
    )
    return record


async def persist_usage_for_user(
    user_id: str,
    response: LLMResponse,
    purpose: str | LLMPurpose = "general",
    trace_id: str | None = None,
) -> None:
    """Best-effort: persist a usage row in a dedicated session. Never raises."""
    try:
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            await record_usage(
                db, response, user_id=user_id, purpose=purpose, trace_id=trace_id
            )
    except Exception as exc:
        # Usage accounting must never break the LLM call — swallow and log.
        logger.warning("llm_usage_persist_failed", user_id=user_id, error=str(exc))
