"""The AI control plane: what the gateway offers, and what has actually been spent on it.

Two halves that used to be missing in opposite ways.

**Providers** were asserted, not discovered — a fixed list of five with invented model names,
each marked "configured" if an API key string happened to be non-empty. This now reads the
gateway's own catalogue (:mod:`app.core.llm.discovery`) and reports what is really routable.

**Usage** was recorded and never shown. ``LLMUsage`` has carried provider, model, prompt and
completion tokens, cost, latency, purpose and status since long before this module; the
settings screen simply never asked. Nothing here estimates or extrapolates: every number is a
SUM over rows the application wrote when it made the call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.llm.discovery import Catalogue, discover
from app.models.llm_usage import LLMUsage
from app.schemas.ai_settings import (
    AICatalogue,
    AIModelInfo,
    AIProviderInfo,
    AIUsageBreakdown,
    AIUsageReport,
)

logger = structlog.get_logger(__name__)

#: Named windows the settings screen offers. ``None`` means "all time" — no cutoff at all,
#: rather than an arbitrarily large one that would quietly exclude old rows.
USAGE_PERIODS: dict[str, timedelta | None] = {
    "today": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}


async def build_catalogue(*, force: bool = False) -> AICatalogue:
    """Providers and models the gateway can actually route to, right now."""
    catalogue: Catalogue = await discover(force=force)
    llm = get_settings().llm
    default_model = llm.default_model

    providers = [
        AIProviderInfo(
            id=provider.id,
            model_count=provider.model_count,
            models=[
                AIModelInfo(
                    id=model.id,
                    provider=model.provider,
                    capabilities=sorted(model.capabilities),
                    # None, never a guess. The UI prints "not reported" — a fabricated
                    # context limit is the kind of number someone would plan around.
                    context_length=model.context_length,
                    max_input_tokens=model.max_input_tokens,
                    max_output_tokens=model.max_output_tokens,
                    is_default=model.id == default_model,
                )
                for model in provider.models
            ],
        )
        for provider in catalogue.providers
    ]

    return AICatalogue(
        reachable=catalogue.reachable,
        error=catalogue.error,
        base_url=catalogue.base_url,
        provider_count=len(providers),
        model_count=catalogue.model_count,
        default_model=default_model,
        # Stated plainly: a default naming a model the gateway does not list is a real
        # misconfiguration, and silently showing it as fine is how it survives.
        default_model_available=bool(
            catalogue.reachable and catalogue.model(default_model) is not None
        ),
        providers=providers,
    )


def _cutoff(period: str) -> datetime | None:
    """The naive-UTC lower bound for a named period, or ``None`` for all time."""
    window = USAGE_PERIODS.get(period, USAGE_PERIODS["7d"])
    if window is None:
        return None
    # The column is timezone-naive UTC, matching the rest of the schema.
    return (datetime.now(UTC) - window).replace(tzinfo=None)


async def build_usage(db: AsyncSession, period: str = "7d") -> AIUsageReport:
    """Real token and cost totals for the current user, from recorded calls only.

    Grouped three ways because the useful question differs: *which model is costing me* is a
    model question, *what is the agent spending it on* is a purpose question, and the provider
    view is what maps onto the catalogue above.
    """
    cutoff = _cutoff(period)

    def scoped(stmt):  # noqa: ANN001, ANN202 - narrow local helper
        return stmt if cutoff is None else stmt.where(LLMUsage.created_at >= cutoff)

    totals = (
        await db.execute(
            scoped(
                select(
                    func.coalesce(func.sum(LLMUsage.prompt_tokens), 0),
                    func.coalesce(func.sum(LLMUsage.completion_tokens), 0),
                    func.coalesce(func.sum(LLMUsage.total_tokens), 0),
                    func.coalesce(func.sum(LLMUsage.cost_usd), 0.0),
                    func.count(LLMUsage.id),
                )
            )
        )
    ).one()
    prompt_tokens, completion_tokens, total_tokens, cost, requests = totals

    errors = (
        await db.execute(
            scoped(
                select(func.count(LLMUsage.id)).where(LLMUsage.error.isnot(None))
            )
        )
    ).scalar() or 0

    async def group_by(column):  # noqa: ANN001, ANN202
        rows = (
            await db.execute(
                scoped(
                    select(
                        column,
                        func.coalesce(func.sum(LLMUsage.total_tokens), 0),
                        func.coalesce(func.sum(LLMUsage.cost_usd), 0.0),
                        func.count(LLMUsage.id),
                    )
                ).group_by(column)
            )
        ).all()
        return sorted(
            (
                AIUsageBreakdown(
                    key=str(key or "unknown"),
                    total_tokens=int(tokens or 0),
                    cost_usd=round(float(spend or 0.0), 6),
                    requests=int(count or 0),
                )
                for key, tokens, spend, count in rows
            ),
            key=lambda b: -b.total_tokens,
        )

    by_provider = await group_by(LLMUsage.provider)
    by_model = await group_by(LLMUsage.model)
    by_purpose = await group_by(LLMUsage.purpose)

    return AIUsageReport(
        period=period if period in USAGE_PERIODS else "7d",
        # False when nothing has been recorded in the window. The UI needs this to say "no
        # calls in this period" rather than presenting a row of confident zeroes.
        recorded=bool(requests),
        requests=int(requests or 0),
        errors=int(errors),
        prompt_tokens=int(prompt_tokens or 0),
        completion_tokens=int(completion_tokens or 0),
        total_tokens=int(total_tokens or 0),
        cost_usd=round(float(cost or 0.0), 6),
        by_provider=by_provider,
        by_model=by_model,
        by_purpose=by_purpose,
        top_model=by_model[0].key if by_model else None,
        top_purpose=by_purpose[0].key if by_purpose else None,
    )
