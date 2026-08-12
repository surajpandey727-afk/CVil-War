"""Apply-pipeline dispatch — the enqueue producer and ``apply_mode`` branching.

This closes the cut wire from the Phase-0 audit: previously nothing ever enqueued an
apply task, so the worker pipeline was unreachable. The route layer calls these after
creating/approving applications.

apply_mode semantics (decision D8):
  * ``autonomous`` — enqueue immediately (status ``queued``).
  * ``review``     — stage for single human approval (status ``pending_review``).
  * ``batch``      — stage for bulk approval (status ``pending_review``); ``bulk_approve``
                     then approves and enqueues a set together.
"""

from __future__ import annotations

import contextlib

import structlog
from arq.connections import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.enums import ApplicationStatus, ApplyMode
from app.observability.metrics import queue_depth

logger = structlog.get_logger(__name__)

APPLY_TASK = "apply_to_job"
_ARQ_QUEUE = "arq:queue"
REVIEW_TASK = "review_application_run"  # harness follow-on job, enqueued after each run


async def enqueue_apply(
    pool: ArqRedis | None, application_id: str, *, defer: int | None = None
) -> str | None:
    """Enqueue the apply task for one application.

    Idempotent: the job id is derived from ``application_id`` so a duplicate enqueue
    (e.g. a double click or retry) is a no-op while a job is still pending. Returns the
    job id, ``None`` on a dedup hit, or ``None`` (logged) if the queue is unavailable.
    """
    if pool is None:
        logger.warning("enqueue_apply.queue_unavailable", application_id=application_id)
        return None
    job = await pool.enqueue_job(
        APPLY_TASK, application_id, _job_id=f"apply:{application_id}", _defer_by=defer
    )
    job_id = job.job_id if job else None
    logger.info("apply_enqueued", application_id=application_id, job_id=job_id)
    with contextlib.suppress(Exception):  # reflect the new backlog (best-effort)
        depth = await pool.llen(_ARQ_QUEUE)  # type: ignore[misc]  # redis-py sync/async union
        queue_depth.labels(queue_name=_ARQ_QUEUE).set(depth)
    return job_id


async def dispatch_for_mode(db: AsyncSession, pool: ArqRedis | None, app: Application) -> None:
    """Set status by ``apply_mode`` and enqueue when autonomous. The single chokepoint
    where ``apply_mode`` stops being cosmetic."""
    if app.apply_mode == ApplyMode.AUTONOMOUS:
        app.status = ApplicationStatus.QUEUED
        await db.commit()
        await db.refresh(app)
        await enqueue_apply(pool, app.id)
    else:  # REVIEW or BATCH — stage for approval; do not enqueue yet.
        app.status = ApplicationStatus.PENDING_REVIEW
        await db.commit()
        await db.refresh(app)


async def bulk_approve(
    db: AsyncSession, pool: ArqRedis | None, application_ids: list[str]
) -> int:
    """Approve a set of staged applications and enqueue them together (batch flow).

    The SELECT is tenant-scoped by the ``do_orm_execute`` filter, so a caller can only
    approve their own applications.
    """
    # Only staged applications may be approved (mirrors approve_application's guard) —
    # otherwise a stale/mixed id list would re-drive terminal or in-flight applications.
    result = await db.execute(
        select(Application).where(
            Application.id.in_(application_ids),
            Application.status.in_(
                (ApplicationStatus.PENDING_REVIEW, ApplicationStatus.QUEUED)
            ),
        )
    )
    apps = list(result.scalars().all())
    for app in apps:
        app.status = ApplicationStatus.APPROVED
    await db.commit()
    for app in apps:
        await enqueue_apply(pool, app.id)
    logger.info("applications_bulk_approved", count=len(apps))
    return len(apps)
