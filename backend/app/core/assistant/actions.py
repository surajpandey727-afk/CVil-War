"""Consequential Assistant actions: propose (returns a token, changes nothing) and execute
(runs only from ``POST /assistant/confirm`` with a valid token).

Every execute path re-checks ownership and state at confirm time — the world may have moved
in the ten minutes since the proposal — and goes through the existing services. Nothing here
submits an application: staging leaves it at ``pending_review``; approval hands it to
``dispatch.bulk_approve``, after which the apply worker and the policy gate decide.
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.core.assistant import tokens
from app.core.assistant import tools as t
from app.core.assistant.context import (
    ToolContext,
    active_role_titles,
    apply_mode_of,
    dumps,
    is_uk,
    owned_job,
    user_settings,
)
from app.core.assistant.loop import ToolOutcome
from app.core.orchestration.recorder import record_agent_run
from app.models.application import Application
from app.models.enums import AgentName, ApplicationStatus, ApplyMode
from app.models.resume import Resume
from app.schemas.application import ApplicationCreate
from app.services import application as app_service
from app.services import dispatch
from app.services.resume_recommendation import recommend_best_resume

logger = structlog.get_logger(__name__)

STAGE = "stage_application"
APPROVE = "approve_applications"
DISCOVER = "run_discovery_now"
#: Discovery fans out to job sources; leave headroom inside the 120 s function limit.
DISCOVERY_TIMEOUT_S = 75.0
_STAGEABLE = (ApplicationStatus.PENDING_REVIEW, ApplicationStatus.QUEUED)


def _proposal(ctx: ToolContext, action: str, params: dict, summary: str) -> ToolOutcome:
    token = tokens.issue(ctx.user_id, action, params)
    content = dumps(
        {
            "needs_confirmation": True,
            "summary": summary,
            "note": "Nothing has happened yet. A Confirm card is shown to the user.",
        }
    )
    return ToolOutcome(
        ok=True,
        content=content,
        summary="awaiting your confirmation",
        pending={"token": token, "summary": summary},
    )


def _refuse(text: str) -> ToolOutcome:
    return ToolOutcome(ok=False, content=text, summary=text[:80])


async def _active_application(ctx: ToolContext, job_id: str) -> Application | None:
    return (
        await ctx.db.execute(
            select(Application).where(
                Application.job_id == job_id,
                Application.status.notin_(app_service._TERMINAL_STATES),
            )
        )
    ).scalar_one_or_none()


async def _resume_name(ctx: ToolContext, resume_id: str) -> str | None:
    row = (
        await ctx.db.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == ctx.user_id)
        )
    ).scalar_one_or_none()
    return row.name if row else None


# -- propose ---------------------------------------------------------------------------------


async def propose_stage(ctx: ToolContext, args: t.StageApplicationInput) -> ToolOutcome:
    job = await owned_job(ctx.db, ctx.user_id, args.job_id)
    if job is None:
        return _refuse("No job with that id.")
    if not is_uk(job):
        return _refuse("That job is outside the UK-only policy, so it can't be applied to.")
    existing = await _active_application(ctx, job.id)
    if existing is not None:
        return ToolOutcome(
            ok=True,
            content=dumps({"already_exists": True, "status": existing.status.value}),
            summary=f"already has an application ({existing.status.value})",
        )
    resume_id = (
        args.resume_id or (await recommend_best_resume(ctx.db, job.id)).recommended_resume_id
    )
    resume_name = await _resume_name(ctx, resume_id) if resume_id else None
    if args.resume_id and resume_name is None:
        return _refuse("No résumé with that id.")
    with_cv = f" with “{resume_name}”" if resume_name else " (no résumé attached yet)"
    summary = (
        f"Stage an application for “{job.title}” at {job.company}{with_cv}. It waits in "
        "Applications as pending review; nothing is submitted."
    )
    return _proposal(ctx, STAGE, {"job_id": job.id, "resume_id": resume_id}, summary)


async def propose_approve(ctx: ToolContext, args: t.ApproveApplicationsInput) -> ToolOutcome:
    rows = list(
        (
            await ctx.db.execute(
                select(Application)
                .where(
                    Application.id.in_(args.application_ids),
                    Application.user_id == ctx.user_id,
                    Application.status.in_(_STAGEABLE),
                )
                .options(selectinload(Application.job))
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return _refuse("None of those applications are waiting for approval.")
    names = ", ".join(f"{a.job.title} at {a.job.company}" if a.job else a.id for a in rows[:5])
    more = f" and {len(rows) - 5} more" if len(rows) > 5 else ""
    summary = (
        f"Approve {len(rows)} application(s): {names}{more}. They join the apply queue; the "
        "apply worker and your automation policy still decide whether each one is submitted."
    )
    return _proposal(ctx, APPROVE, {"application_ids": [a.id for a in rows]}, summary)


async def propose_discovery(ctx: ToolContext, _: t.NoInput) -> ToolOutcome:
    titles = active_role_titles(await user_settings(ctx.db, ctx.user_id))
    if not titles:
        return _refuse("No active role targets to search for. Add some in Role targets first.")
    summary = (
        f"Run discovery now for {len(titles[:5])} role target(s): {', '.join(titles[:5])}. "
        "This searches your enabled job sources and can take up to a minute."
    )
    return _proposal(ctx, DISCOVER, {}, summary)


# -- execute ---------------------------------------------------------------------------------


async def execute(ctx: ToolContext, pending: tokens.PendingAction) -> tuple[bool, str]:
    """Run a verified pending action. Returns ``(ok, message for the user)``."""
    if pending.action == STAGE:
        return await _do_stage(ctx, pending.params)
    if pending.action == APPROVE:
        return await _do_approve(ctx, pending.params)
    if pending.action == DISCOVER:
        return await _do_discovery(ctx)
    return False, "Unknown action."


async def _do_stage(ctx: ToolContext, params: dict) -> tuple[bool, str]:
    job = await owned_job(ctx.db, ctx.user_id, str(params.get("job_id", "")))
    if job is None or not is_uk(job):
        return False, "That job is no longer available to apply to."
    if (existing := await _active_application(ctx, job.id)) is not None:
        return True, f"An application for {job.title} already exists ({existing.status.value})."
    mode = apply_mode_of(await user_settings(ctx.db, ctx.user_id))
    resume_id = params.get("resume_id") or None
    app = await app_service.create_application(
        ctx.db, ApplicationCreate(job_id=job.id, resume_id=resume_id, apply_mode=mode), ctx.user_id
    )
    if mode == ApplyMode.AUTONOMOUS:
        # dispatch_for_mode would enqueue it straight away. Anything the assistant creates
        # waits for the user's approval, whatever the global mode.
        app.status = ApplicationStatus.PENDING_REVIEW
        await ctx.db.commit()
        await ctx.db.refresh(app)
    else:
        await dispatch.dispatch_for_mode(ctx.db, ctx.pool, app)
    logger.info("assistant.application_staged", app_id=app.id, job_id=job.id)
    return True, (
        f"Staged: {job.title} at {job.company} is waiting for your review in Applications."
    )


async def _do_approve(ctx: ToolContext, params: dict) -> tuple[bool, str]:
    requested = [str(i) for i in params.get("application_ids", [])][:20]
    # Explicit owner filter on top of the tenant-scoped session: belt and braces.
    ids = list(
        (
            await ctx.db.execute(
                select(Application.id).where(
                    Application.id.in_(requested), Application.user_id == ctx.user_id
                )
            )
        )
        .scalars()
        .all()
    )
    count = await dispatch.bulk_approve(ctx.db, ctx.pool, ids) if ids else 0
    if count == 0:
        return False, "Nothing was approved: those applications are no longer waiting."
    if ctx.pool is not None:
        where = "They're in the apply queue."
    elif get_settings().apply_dispatch == "db_queue":
        where = "They're waiting for the apply worker to pick them up."
    else:
        where = "They went through the apply pipeline here; check Applications for each result."
    return True, f"Approved {count} application(s). {where} The policy gate decides each submit."


async def _do_discovery(ctx: ToolContext) -> tuple[bool, str]:
    from app.services.discovery_scheduler import _discover_for_user

    try:
        async with record_agent_run(
            ctx.db,
            ctx.user_id,
            AgentName.DISCOVERY,
            input_summary="Assistant: run discovery now",
            linked_entity_type="user",
            linked_entity_id=ctx.user_id,
            redis=ctx.redis,
        ) as run:
            found = await asyncio.wait_for(
                _discover_for_user(ctx.db, ctx.user_id), timeout=DISCOVERY_TIMEOUT_S
            )
            run.output_summary = f"{found} job(s) found"
    except TimeoutError:
        return (
            False,
            "Discovery took too long and was stopped. Try again, or wait for the schedule.",
        )
    except Exception as exc:
        logger.warning("assistant.discovery_failed", error=type(exc).__name__)
        return False, "Discovery failed. The Discovery agent's log in AI Agents has the detail."
    return True, f"Discovery finished: {found} job(s) found. New UK roles are in Jobs."
