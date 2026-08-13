"""Arq worker tasks — the reachable apply pipeline (Phase 1).

This is the live consumer fed by ``services.dispatch.enqueue_apply``. It supersedes the
legacy raw-Redis ``application_worker.py`` (kept until Phase 2 absorbs its ATS-scoring
logic). The actual browser submission (``_submit_application``) is a placeholder until
Phase 2 wires the hardened browser-use backbone; everything around it — idempotency,
the status lifecycle, progress events, and retry classification — is real.

Run with: ``arq app.workers.tasks.WorkerSettings``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

import structlog
from arq import Retry, cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.websocket.bus import publish_progress
from app.config.settings import get_settings
from app.core.exceptions import LLMRateLimitError, LLMTimeoutError
from app.core.harness.anomaly import detect_anomalies
from app.core.harness.review import review_run
from app.core.harness.skills import add_feedback
from app.core.llm.factory import build_llm_client_for_user
from app.db.session import async_session_factory
from app.db.tenant import current_user_id
from app.models.application import Application
from app.models.enums import (
    ApplicationStatus,
    ConfirmationState,
    RunVerdictResult,
    SubmissionMethod,
)
from app.models.harness import RunTrajectory
from app.models.job import Job
from app.observability.metrics import (
    applications_total,
    queue_depth,
    queue_processing_duration_seconds,
)

logger = structlog.get_logger(__name__)

_ARQ_QUEUE = "arq:queue"  # Arq's default queue list key
MAX_TRIES = 3  # shared by WorkerSettings.max_tries and the retry-exhaustion check

# Substrings marking a retryable infrastructure failure (vs a terminal non-submission).
_TRANSIENT_HINTS = (
    "rate limit", "timeout", "timed out", "429", "503", "502",
    "connection", "temporarily", "unavailable", "network",
)


class TransientApplyError(Exception):
    """A retryable apply failure (network blip, anti-bot challenge, rate limit)."""


def _is_transient(exc: Exception) -> bool:
    """True if an apply error looks like a retryable infrastructure blip."""
    text = str(exc).lower()
    return any(hint in text for hint in _TRANSIENT_HINTS)


async def _publish(
    ctx: dict[str, Any], user_id: str, application_id: str, status: str, detail: str = ""
) -> None:
    """Publish a progress event over the Redis bus (no-op if no redis in ctx)."""
    redis = ctx.get("redis")
    if redis is None:
        return
    await publish_progress(
        redis,
        user_id,
        {
            "type": "application_progress",
            "payload": {"application_id": application_id, "status": status, "detail": detail},
        },
    )


async def _submit_application(
    db: AsyncSession, app: Application, redis: Any | None = None
) -> str:
    """Submit the application.

    Default (``BROWSER__LIVE_APPLY`` false): a provable placeholder so the end-to-end
    queue → worker → status loop is CI-safe and demoable. When enabled (real browser +
    assisted-login session), drives the live browser-use apply via ``run_apply``; a
    missing session/key surfaces as ``ApplyPrerequisiteError`` → terminal FAILED. ``redis``
    is threaded through so the live run can publish per-step progress and enqueue the
    harness review job.
    """
    if not get_settings().browser.live_apply:
        logger.info("apply.placeholder_submit", application_id=app.id)
        # Nothing was sent anywhere. Recorded as SIMULATED rather than returning a
        # confirmation-shaped string, which is what made a rehearsal indistinguishable from a
        # real submission in every downstream view.
        app.submission_method = SubmissionMethod.SIMULATED
        app.confirmation_state = ConfirmationState.SIMULATED
        app.confirmation_detail = (
            "Live apply is disabled (BROWSER__LIVE_APPLY=false), so no browser ran and "
            "nothing was submitted to the employer."
        )
        return ""

    from app.core.automation.runtime.apply import ApplyPrerequisiteError, run_apply

    try:
        result = await run_apply(db, app, redis=redis)
    except ApplyPrerequisiteError:
        raise  # missing session/key/resume — retrying won't help; let it be terminal
    except Exception as exc:
        # Reclassify retryable infra failures so Arq's retry/backoff is actually used.
        if _is_transient(exc):
            raise TransientApplyError(str(exc)) from exc
        raise
    if not result.submitted:
        raise RuntimeError(result.notes or "Submission not confirmed by the agent")
    app.submission_method = SubmissionMethod.AUTOMATED
    # A confirmation id means the portal acknowledged the submission and the agent could read
    # it back. Without one the run finished cleanly but nothing corroborates it, and saying
    # so is the whole point of the distinction.
    reference = (result.confirmation_id or "").strip()
    app.confirmation_state = (
        ConfirmationState.CONFIRMED if reference else ConfirmationState.UNCONFIRMED
    )
    app.confirmation_detail = (result.notes or "").strip()[:500] or None
    if reference:
        app.external_reference = reference[:200]
    return reference


async def _ats_score(db: AsyncSession, app: Application) -> float | None:
    """Score the attached résumé against the posting, or ``None`` if it could not be scored.

    ``None`` is load-bearing and is not the same as 0.0: the policy's match rule escalates an
    unscoreable application rather than passing it, so an unavailable scorer can no longer
    make the gate silently optional. This function used to *be* the gate and returned
    ``(ok, score)`` with a hardcoded threshold; the decision now belongs to
    :mod:`app.core.policy`.
    """
    if not app.resume_id:
        # No CV attached. The stored score, if the matching service recorded one at
        # discovery, is the best evidence available; otherwise this genuinely is unscored and
        # the policy escalates rather than submitting an application with no CV behind it.
        return app.ats_score
    from app.schemas.resume import ResumeScoreRequest
    from app.services import resume as resume_service

    try:
        resp = await resume_service.score_resume(
            db, app.resume_id, ResumeScoreRequest(job_id=app.job_id)
        )
    except Exception as exc:
        logger.warning("apply.ats_score_unavailable", application_id=app.id, error=str(exc))
        return app.ats_score
    return resp.overall_score


async def _enforce_policy(
    db: AsyncSession, ctx: dict[str, Any], app: Application, platform: str
) -> bool:
    """Run the automation policy gate. Returns True only if the submission may proceed.

    Each refusal has a different resting place, and conflating them is what produces dead
    ends: a HOLD goes back on the queue with a wake-up time, an ESCALATE lands in the review
    queue for a human, a BLOCK is terminal. Every one of them is already on the timeline with
    its reasons by the time this returns — see ``services.policy.gate``.
    """
    from app.core.policy import Verdict
    from app.services.dispatch import enqueue_apply
    from app.services.policy import gate

    score = await _ats_score(db, app)
    decision = await gate(db, app, ats_score=score)
    if decision.verdict is Verdict.ALLOW:
        await db.commit()
        return True

    reason = decision.summary
    if decision.verdict is Verdict.HOLD:
        app.status = ApplicationStatus.QUEUED
        app.notes = reason
        await db.commit()
        # Wake it up when the earliest hold could clear. Capped at an hour so a rule that
        # names a distant time (a 90-day cooldown) still gets re-checked against a policy the
        # operator may have changed in the meantime.
        delay = 3600
        if decision.retry_after:
            wait = (decision.retry_after - datetime.now(UTC)).total_seconds()
            delay = max(30, min(int(wait), 3600))
        await enqueue_apply(
            ctx.get("redis"),
            app.id,
            defer=delay,
            job_id=f"apply:{app.id}:hold:{int(time.time()) + delay}",
        )
        await _publish(ctx, app.user_id, app.id, ApplicationStatus.QUEUED.value, reason)
        logger.info("apply.policy_hold", application_id=app.id, delay=delay, reason=reason)
        return False

    if decision.verdict is Verdict.ESCALATE:
        app.status = ApplicationStatus.PENDING_REVIEW
        app.notes = reason
        await db.commit()
        await _publish(
            ctx, app.user_id, app.id, ApplicationStatus.PENDING_REVIEW.value, reason
        )
        logger.info("apply.policy_escalate", application_id=app.id, reason=reason)
        return False

    await _mark_failed(db, ctx, app, platform, reason)
    return False


async def _mark_failed(
    db: AsyncSession, ctx: dict[str, Any], app: Application, platform: str, note: str
) -> None:
    """Transition an application to terminal FAILED + emit the metric and progress event."""
    app.status = ApplicationStatus.FAILED
    app.notes = note
    # A failed attempt never reached the employer; leaving confirmation_state at PENDING
    # would let the evidence panel imply a submission was still in flight.
    app.confirmation_state = ConfirmationState.FAILED
    await db.commit()
    applications_total.labels(status="failed", platform=platform).inc()
    await _publish(ctx, app.user_id, app.id, ApplicationStatus.FAILED.value, note)
    logger.error("apply.permanent_failure", application_id=app.id, note=note)


async def _apply(db: AsyncSession, ctx: dict[str, Any], application_id: str) -> None:
    """Core apply logic against a provided session (extracted for testability).

    The application is loaded UNSCOPED (the worker has no ambient tenant); the tenant
    contextvar is then set to the row's owner for the rest of the job and reset at the
    end so concurrent jobs never inherit each other's scope.
    """
    job_try: int = ctx.get("job_try", 1)
    token = current_user_id.set(None)
    try:
        app = await db.get(Application, application_id)
        if app is None:
            logger.warning("apply.app_not_found", application_id=application_id)
            return

        # Scope subsequent queries to the row's owner.
        current_user_id.set(app.user_id)

        # Idempotency: never re-submit a completed application (guards at-least-once retries).
        if app.status == ApplicationStatus.APPLIED:
            logger.info("apply.already_applied", application_id=application_id)
            return

        job = await db.get(Job, app.job_id)
        platform = job.platform if job else "unknown"

        # The automation policy gate — the one place submission is permitted or refused.
        if not await _enforce_policy(db, ctx, app, platform):
            return

        # In-flight marker, committed before the (non-transactional) submit.
        app.status = ApplicationStatus.APPLYING
        await db.commit()
        await _publish(ctx, app.user_id, application_id, ApplicationStatus.APPLYING.value)

        try:
            confirmation = await _submit_application(db, app, ctx.get("redis"))
        except TransientApplyError as exc:
            if job_try >= MAX_TRIES:
                # Retries exhausted — transition to terminal FAILED rather than leaving
                # the row stuck in APPLYING forever (Arq won't re-invoke after this).
                await _mark_failed(
                    db, ctx, app, platform, f"Apply failed after {job_try} attempts: {exc}"
                )
                return
            logger.warning(
                "apply.transient_failure",
                application_id=application_id,
                job_try=job_try,
                error=str(exc),
            )
            raise Retry(defer=job_try * 30) from exc
        except asyncio.CancelledError:
            # job_timeout cancels the coroutine (CancelledError is not an Exception) —
            # record the terminal failure best-effort, then let the cancellation propagate.
            with contextlib.suppress(Exception):
                await _mark_failed(db, ctx, app, platform, "Apply cancelled (timeout)")
            raise
        except Exception as exc:  # any non-transient failure is terminal
            await _mark_failed(db, ctx, app, platform, f"Apply failed: {exc}")
            return

        app.status = ApplicationStatus.APPLIED
        app.applied_at = datetime.now(UTC)
        await db.commit()
        applications_total.labels(status="applied", platform=platform).inc()
        await _publish(ctx, app.user_id, application_id, ApplicationStatus.APPLIED.value)
        logger.info("apply.applied", application_id=application_id, confirmation=confirmation)
    finally:
        current_user_id.reset(token)


async def _update_queue_depth(redis: Any | None) -> None:
    """Best-effort: publish the current Arq backlog to the queue_depth gauge."""
    if redis is None:
        return
    try:
        queue_depth.labels(queue_name=_ARQ_QUEUE).set(await redis.llen(_ARQ_QUEUE))
    except Exception as exc:  # a metric read must never fail the job
        logger.debug("queue_depth.read_failed", error=str(exc))


async def run_apply_pipeline(ctx: dict[str, Any], application_id: str) -> None:
    """Open a session and run the apply pipeline, timing it for the queue histogram."""
    await _update_queue_depth(ctx.get("redis"))
    start = time.perf_counter()
    try:
        async with async_session_factory() as db:
            await _apply(db, ctx, application_id)
    finally:
        queue_processing_duration_seconds.labels(queue_name=_ARQ_QUEUE).observe(
            time.perf_counter() - start
        )


async def apply_to_job(ctx: dict[str, Any], application_id: str) -> None:
    """Arq task entry point (registered name ``apply_to_job``)."""
    await run_apply_pipeline(ctx, application_id)


async def review_application_run(
    ctx: dict[str, Any], run_id: str, signals: dict[str, Any] | None = None
) -> None:
    """Harness follow-on: judge → diagnose → distil a finished run (registered task).

    Loads the trajectory UNSCOPED (the worker has no ambient tenant), sets the tenant
    contextvar to the run's owner, builds that user's LLM client, and runs the review.
    """
    token = current_user_id.set(None)
    try:
        async with async_session_factory() as db:
            traj = await db.get(RunTrajectory, run_id)
            if traj is None:
                logger.warning("review.trajectory_not_found", run_id=run_id)
                return
            current_user_id.set(traj.user_id)
            llm = await build_llm_client_for_user(db, traj.user_id)
            outcome = await review_run(db, llm, traj, signals or {})
            await _score_skills_from_verdict(db, traj, outcome.get("verdict"))
            logger.info("review.complete", run_id=run_id, **outcome)
    except (LLMRateLimitError, LLMTimeoutError):
        # Transient provider error — let Arq retry the review job (max_tries) instead of
        # silently dropping this run's verdict + skill feedback.
        logger.warning("review.transient_error_retrying", run_id=run_id)
        raise
    except Exception as exc:
        logger.error("review.failed", run_id=run_id, error=str(exc))
    finally:
        current_user_id.reset(token)


async def _score_skills_from_verdict(db: AsyncSession, traj: RunTrajectory, verdict: Any) -> None:
    """Close the self-evolving loop: +1 to every skill used on a success, -1 otherwise.

    Skills that repeatedly correlate with failure drift below the retire threshold and are
    auto-retired by ``add_feedback``.
    """
    skill_ids = traj.skills_used or []
    if not skill_ids:
        return
    delta = 1 if verdict == RunVerdictResult.SUCCESS else -1
    for skill_id in skill_ids:
        await add_feedback(db, skill_id, delta, reason=f"run verdict={verdict}", run_id=traj.id)


async def monitor_system_health(ctx: dict[str, Any]) -> None:
    """Scheduled harness self-monitoring (Arq cron): persist any detected SystemIssue rows."""
    async with async_session_factory() as db:
        issues = await detect_anomalies(db, redis=ctx.get("redis"))
    logger.info("monitor.system_health", issue_count=len(issues))


async def purge_deleted_accounts(ctx: dict[str, Any]) -> None:
    """Scheduled (Arq cron): hard-purge accounts soft-deleted past the grace period (D9)."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.models.user import User
    from app.services.account import PURGE_GRACE_DAYS, delete_user_data

    cutoff = datetime.now(UTC) - timedelta(days=PURGE_GRACE_DAYS)
    async with async_session_factory() as db:
        user_ids = (
            await db.execute(
                select(User.id).where(User.deleted_at.isnot(None), User.deleted_at < cutoff)
            )
        ).scalars().all()
        purged = 0
        for user_id in user_ids:
            result = await delete_user_data(db, user_id)
            purged += result.get("purged", 0)
    # `purged` counts accounts actually removed; the rest aborted on storage failure → retried.
    logger.info("purge.run_complete", purged=purged, candidates=len(user_ids))


async def _on_startup(ctx: dict[str, Any]) -> None:
    from app.observability.sentry import init_sentry

    init_sentry("worker")  # no-op unless SENTRY_DSN is set
    logger.info("worker.startup")


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker.shutdown")


class WorkerSettings:
    """Arq worker configuration."""

    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions: ClassVar = [apply_to_job, review_application_run]
    cron_jobs: ClassVar = [
        cron(monitor_system_health, minute={0, 15, 30, 45}),
        cron(purge_deleted_accounts, hour={3}, minute={30}),  # daily 03:30
    ]
    max_jobs = get_settings().browser.max_parallel
    job_timeout = 600
    max_tries = MAX_TRIES
    on_startup = _on_startup
    on_shutdown = _on_shutdown
