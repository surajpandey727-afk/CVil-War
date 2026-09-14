"""User settings API routes with per-user database persistence."""

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.config.settings import get_settings as get_app_settings
from app.core.policy import POLICY_VERSION, RULES, TAG_TITLES, AutomationPolicy, evaluate
from app.core.secrets import CredentialStore
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.user_credential import UserCredential
from app.models.user_llm_config import UserLLMConfig
from app.models.user_settings import UserSettings
from app.schemas.ai_settings import AICatalogue, AIUsageReport
from app.schemas.platforms import (
    PlatformBulkUpdate,
    PlatformsResponse,
    PlatformTestRequest,
    PlatformTestResponse,
)
from app.schemas.settings import (
    BYOLLMKeyStatus,
    BYOLLMKeyUpdate,
    LLMProviderStatus,
    PolicyCatalogue,
    PolicyControl,
    PolicyGroup,
    PolicyPreview,
    PolicyPreviewItem,
    PolicyRuleInfo,
    SettingsResponse,
    SettingsUpdate,
    SponsorshipRegisterRefreshResult,
    SponsorshipRegisterStatus,
)
from app.services import platforms as platform_service
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
    "/platforms",
    response_model=PlatformsResponse,
    summary="Every job source, with this user's enablement and connection state",
)
async def list_platforms(
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> PlatformsResponse:
    """The platform control plane, assembled from the same registry the Sources screen reads.

    One source of truth on purpose: Settings previously hard-coded four platforms while the
    registry served fifty-five, so the two screens disagreed about what the product supports.
    Available actions are decided here, because whether a source needs a login — or can be
    tested at all — depends on the adapter, not on anything the browser knows.
    """
    return await platform_service.list_platforms(db, user.id)


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


@router.put(
    "/llm-key",
    response_model=BYOLLMKeyStatus,
    summary="Save a BYO LLM provider API key",
)
async def save_llm_key(
    body: BYOLLMKeyUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> BYOLLMKeyStatus:
    """Encrypt and store the key; the value itself is never returned by any endpoint.

    ``build_llm_client_for_user`` (the actual consumer, in ``core.llm.factory``) already
    reads exactly this storage — the missing piece was a way for the operator to write to
    it at all. Every generation path (résumé tailoring, cover letters, fit analysis) was
    already wired to a feature the product's own landing page advertises as a headline
    capability, but which had no route and no UI.
    """
    await CredentialStore().put_llm_key(db, user.id, body.provider, body.api_key)

    config = (
        await db.execute(select(UserLLMConfig).where(UserLLMConfig.user_id == user.id))
    ).scalar_one_or_none()
    if config is None:
        config = UserLLMConfig(user_id=user.id)
        db.add(config)
    if body.make_active:
        config.preferred_provider = body.provider
        if body.default_model:
            config.default_model = body.default_model
    await db.commit()
    await db.refresh(config)

    return BYOLLMKeyStatus(
        provider=body.provider,
        has_key=True,
        is_active=config.preferred_provider == body.provider,
        default_model=config.default_model if config.preferred_provider == body.provider else None,
    )


@router.get(
    "/llm-key",
    response_model=list[BYOLLMKeyStatus],
    summary="List which providers have a BYO key stored",
)
async def list_llm_keys(
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> list[BYOLLMKeyStatus]:
    """Never returns a key value — only whether one exists, per provider."""
    config = (
        await db.execute(select(UserLLMConfig).where(UserLLMConfig.user_id == user.id))
    ).scalar_one_or_none()
    rows = (
        await db.execute(
            select(UserCredential.provider).where(
                UserCredential.user_id == user.id, UserCredential.kind == "llm_key",
            )
        )
    ).scalars().all()
    results = []
    for provider in rows:
        is_active = bool(config and config.preferred_provider == provider)
        results.append(
            BYOLLMKeyStatus(
                provider=provider,
                has_key=True,
                is_active=is_active,
                default_model=config.default_model if is_active and config else None,
            )
        )
    return results


@router.delete(
    "/llm-key/{provider}",
    status_code=204,
    summary="Remove a stored BYO LLM provider key",
)
async def delete_llm_key(
    provider: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    await db.execute(
        delete(UserCredential).where(
            UserCredential.user_id == user.id,
            UserCredential.kind == "llm_key",
            UserCredential.provider == provider,
        )
    )
    await db.commit()


@router.post(
    "/platforms/test",
    response_model=PlatformTestResponse,
    summary="Probe sources for real and report what actually answered",
)
async def test_platforms(
    request: PlatformTestRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> PlatformTestResponse:
    """Run every selected adapter's live health check and return the results.

    The Settings screen rendered a "Test" control that no endpoint served, so an operator
    looking at fifty-five catalogued sources had no way to establish that any of them worked —
    "Settings shows them but nothing works, how can I verify?" was the entirely reasonable
    conclusion. Each result here is a request made moments ago, carrying the upstream's own
    words on failure rather than a generic message.

    An empty ``keys`` list probes everything with a working adapter.
    """
    return await platform_service.test_platforms(db, user.id, request.keys or None)


@router.put(
    "/platforms/bulk",
    response_model=PlatformsResponse,
    summary="Enable or disable many sources at once",
)
async def bulk_update_platforms(
    update: PlatformBulkUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> PlatformsResponse:
    """Switch a set of sources on or off in one write.

    Toggling fifty-five sources one request at a time is the kind of thing software should do
    for you. Applied as a single update so a partial failure cannot leave the selection half
    applied, and the refreshed platform list comes back so the screen needs no second call.
    """
    settings = await _get_or_create_settings(db, user.id)
    current = set(settings.platforms_enabled or [])
    requested = {k.strip().lower() for k in update.keys if k.strip()}

    settings.platforms_enabled = sorted(
        current | requested if update.enabled else current - requested
    )
    await db.commit()
    logger.info(
        "platforms_bulk_updated",
        user_id=user.id, count=len(requested), enabled=update.enabled,
    )
    return await platform_service.list_platforms(db, user.id)


@router.get(
    "/sponsorship-register/status",
    response_model=SponsorshipRegisterStatus,
    summary="Cached status of the UK sponsor register",
)
async def sponsorship_register_status(user: CurrentUser) -> SponsorshipRegisterStatus:
    """Last refresh time and row count of the cached register. Never triggers a download —
    use the refresh endpoint for that. ``stale`` reflects the same 7-day window the weekly
    background refresh (``workers.tasks.refresh_sponsor_register``) is meant to keep ahead of."""
    from app.core.sponsorship import register

    return SponsorshipRegisterStatus(**register.status())


@router.post(
    "/sponsorship-register/refresh",
    response_model=SponsorshipRegisterRefreshResult,
    summary="Download the current UK sponsor register",
)
async def sponsorship_register_refresh(
    user: CurrentUser, force: bool = False
) -> SponsorshipRegisterRefreshResult:
    """Manually trigger a download, e.g. right after setup or if the weekly cron missed a run.

    Failure (network, or the gov.uk page layout changing) is reported in the response rather
    than raised as a 500 — a stale-but-present register is still useful, so this never wipes
    a working cache on a failed attempt.
    """
    from app.core.sponsorship import register

    try:
        await register.refresh(force=force)
    except Exception as exc:
        logger.warning("sponsorship_register.refresh_failed", error=str(exc))
        return SponsorshipRegisterRefreshResult(
            **register.status(), refreshed=False, error=str(exc)
        )
    return SponsorshipRegisterRefreshResult(**register.status(), refreshed=True)
