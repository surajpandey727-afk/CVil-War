"""User settings API routes with per-user database persistence."""

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.config.settings import get_settings as get_app_settings
from app.core.policy import POLICY_VERSION, RULES, TAG_TITLES, AutomationPolicy, evaluate
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.user_settings import UserSettings
from app.schemas.ai_settings import AICatalogue, AIUsageReport
from app.schemas.settings import (
    LLMProviderStatus,
    PolicyCatalogue,
    PolicyControl,
    PolicyGroup,
    PolicyPreview,
    PolicyPreviewItem,
    PolicyRuleInfo,
    SettingsResponse,
    SettingsUpdate,
)
from app.services.ai_settings import build_catalogue, build_usage
from app.services.policy import build_context, load_policy

logger = structlog.get_logger(__name__)
router = APIRouter()

#: Ceiling on a preview run. Each application costs a handful of counting queries, and the
#: operator does not need every row to see the shape of a change.
_PREVIEW_LIMIT = 50


async def _get_or_create_settings(db: AsyncSession, user_id: str) -> UserSettings:
    """Return the user's settings row, creating defaults if absent."""
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        try:
            await db.commit()
        except IntegrityError:
            # Concurrent first-write from the same user — re-fetch the winner's row.
            await db.rollback()
            settings = (
                await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
            ).scalar_one()
        else:
            await db.refresh(settings)
            logger.info("settings_created_defaults", user_id=user_id)
    return settings


@router.get("/", response_model=SettingsResponse, summary="Get current settings")
async def get_settings(
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> SettingsResponse:
    """Get the current user's settings from the database."""
    settings = await _get_or_create_settings(db, user.id)
    return SettingsResponse.model_validate(settings)


@router.put("/", response_model=SettingsResponse, summary="Update settings")
async def update_settings(
    update: SettingsUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> SettingsResponse:
    """Update the current user's settings. Only provided fields are changed."""
    settings = await _get_or_create_settings(db, user.id)

    # ``mode="json"`` matters: `candidate_profile`, `role_targets` and `automation` are nested
    # Pydantic models bound to JSON columns. Without it SQLAlchemy is handed model instances
    # and the JSON serializer raises at flush time.
    update_data = update.model_dump(exclude_unset=True, mode="json")
    for field, value in update_data.items():
        setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)

    logger.info("settings_updated", user_id=user.id, changed_fields=list(update_data.keys()))
    return SettingsResponse.model_validate(settings)


@router.get(
    "/automation-policy",
    response_model=PolicyCatalogue,
    summary="The automation policy: every clause, its control, and the current value",
)
async def get_automation_policy(
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> PolicyCatalogue:
    """Return the rule catalogue joined to this user's stored values.

    The automation screen builds itself from this rather than hard-coding controls, which is
    what keeps the UI, the enforced rules and ``docs/AUTOMATION_POLICY.md`` from drifting
    apart — a new clause shows up with its own bounds and rationale attached.
    """
    policy = await load_policy(db, user.id)
    by_tag: dict[str, list[PolicyRuleInfo]] = {}
    for rule in RULES:
        info = PolicyRuleInfo(
            id=rule.id,
            clause=rule.clause,
            title=rule.title,
            rationale=rule.rationale,
            enforcement=rule.enforcement.value,
            verdict=rule.verdict.value,
            locked=rule.locked,
            control=PolicyControl(
                kind=rule.control.kind.value,
                min=rule.control.min,
                max=rule.control.max,
                step=rule.control.step,
                unit=rule.control.unit,
                options=rule.control.options,
            ),
            field_name=rule.field_name,
            enforced_by=rule.enforced_by,
            value=getattr(policy, rule.field_name, None) if rule.field_name else None,
        )
        for tag in rule.tags or ("other",):
            by_tag.setdefault(tag, []).append(info)

    groups = [
        PolicyGroup(id=tag, title=title, rules=by_tag[tag])
        for tag, title in TAG_TITLES
        if by_tag.get(tag)
    ]
    return PolicyCatalogue(policy_version=POLICY_VERSION, groups=groups, policy=policy)


@router.post(
    "/automation-policy/preview",
    response_model=PolicyPreview,
    summary="Dry-run a candidate policy against everything currently queued",
)
async def preview_automation_policy(
    candidate: AutomationPolicy,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> PolicyPreview:
    """Evaluate an unsaved policy against the operator's waiting applications.

    Nothing is written — ``record=False`` keeps a preview off the timeline, and the candidate
    policy is never persisted. The point is to make a threshold change reviewable before it
    takes effect rather than discovering its blast radius afterwards.
    """
    result = await db.execute(
        select(Application)
        .where(
            Application.status.in_(
                (
                    ApplicationStatus.QUEUED,
                    ApplicationStatus.PENDING_REVIEW,
                    ApplicationStatus.APPROVED,
                )
            )
        )
        .order_by(Application.created_at.desc())
        .limit(_PREVIEW_LIMIT)
    )
    applications = list(result.scalars().all())

    preview = PolicyPreview(evaluated=len(applications))
    for app in applications:
        job = await db.get(Job, app.job_id)
        ctx = await build_context(db, app, job, ats_score=app.ats_score)
        decision = evaluate(candidate, ctx)
        setattr(preview, decision.verdict.value, getattr(preview, decision.verdict.value) + 1)
        preview.items.append(
            PolicyPreviewItem(
                application_id=app.id,
                job_title=job.title if job else "",
                company=job.company if job else "",
                verdict=decision.verdict.value,
                reasons=[o.reason for o in decision.outcomes if o.reason],
                rule_ids=[o.rule_id for o in decision.outcomes],
            )
        )
    return preview


@router.get(
    "/ai/catalogue",
    response_model=AICatalogue,
    summary="Providers and models the configured gateway can actually route to",
)
async def get_ai_catalogue(
    refresh: bool = Query(
        False, description="Bypass the cache and re-query the gateway now."
    ),
) -> AICatalogue:
    """Discover providers, models, capabilities and context limits from the LLM gateway.

    Queried live rather than declared. The list this replaced was five hard-coded providers
    with invented model names (``gpt-4o``, ``gemini-pro``) that the configured gateway does
    not offer, each reported as "configured" purely because an API key string was non-empty.
    """
    return await build_catalogue(force=refresh)


@router.get(
    "/ai/usage",
    response_model=AIUsageReport,
    summary="Recorded LLM token usage and cost",
)
async def get_ai_usage(
    user: CurrentUser,
    period: str = Query("7d", description="today | 7d | 30d | all"),
    db: AsyncSession = Depends(get_tenant_db),
) -> AIUsageReport:
    """Token and cost totals summed from the calls this account actually made.

    Every figure is a SUM over ``llm_usage`` rows written at call time — nothing is estimated
    or extrapolated. A period with no calls reports ``recorded: false`` rather than zeroes,
    which would read as "measured, and it was nothing".
    """
    return await build_usage(db, period)


@router.get(
    "/llm-providers",
    response_model=list[LLMProviderStatus],
    summary="List LLM provider statuses (legacy; prefer /ai/catalogue)",
    deprecated=True,
)
async def list_llm_providers() -> list[LLMProviderStatus]:
    """Provider statuses, now derived from the gateway rather than a hard-coded list.

    Kept so existing clients keep working, but it can only ever be a lossy view of
    ``/ai/catalogue``: this shape has one model per provider and the gateway routinely offers
    hundreds. New callers should use the catalogue.
    """
    catalogue = await build_catalogue()
    llm = get_app_settings().llm
    if not catalogue.reachable:
        return []
    return [
        LLMProviderStatus(
            provider=provider.id,
            # "Configured" now means the gateway lists routable models for it, not that a
            # key string was non-empty somewhere in the environment.
            configured=provider.model_count > 0,
            model=next(
                (m.id for m in provider.models if m.is_default),
                provider.models[0].id if provider.models else "",
            ),
            is_primary=any(m.is_default for m in provider.models)
            or llm.preferred_provider == provider.id,
        )
        for provider in catalogue.providers
    ]
