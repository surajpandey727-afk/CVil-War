"""Internal webhook targets for external automation (n8n): trigger a scheduled cycle now.

Not user-JWT-authenticated — n8n has no interactive login, so these are gated by a single
static bearer token instead (``INTERNAL_WEBHOOK_TOKEN``), compared in constant time exactly
like ``main.py``'s own ``/metrics`` guard. Both endpoints enqueue the SAME Arq task the
scheduled cron already runs (see ``workers.tasks.WorkerSettings``) — an n8n-triggered "sync
now" can never drift from what the schedule itself does, because it is not a second
implementation.

Arq stays the one real scheduler; n8n is a second way to ask it to run a cycle immediately
(e.g. from a webhook, a Slack slash command, or any other trigger n8n itself understands),
not a competing scheduler.
"""

from __future__ import annotations

import hmac

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Header, HTTPException

from app.config.settings import get_settings
from app.db.arq import get_arq_pool

logger = structlog.get_logger(__name__)
router = APIRouter()


def _check_token(authorization: str | None) -> None:
    token = get_settings().internal_webhook_token.get_secret_value()
    if not token or not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="Invalid or missing internal webhook token")


@router.post("/discovery/run", summary="Trigger a discovery cycle now (n8n webhook target)")
async def trigger_discovery(
    authorization: str | None = Header(default=None),
    pool: ArqRedis | None = Depends(get_arq_pool),
) -> dict:
    _check_token(authorization)
    if pool is None:
        raise HTTPException(status_code=503, detail="Job queue unavailable")
    job = await pool.enqueue_job("run_discovery_for_all_users", _job_id="internal:discovery:run")
    logger.info("internal.discovery_triggered", job_id=job.job_id if job else None)
    return {"queued": job is not None}


@router.post("/inbox-sync/run", summary="Trigger a Gmail sync cycle now (n8n webhook target)")
async def trigger_inbox_sync(
    authorization: str | None = Header(default=None),
    pool: ArqRedis | None = Depends(get_arq_pool),
) -> dict:
    _check_token(authorization)
    if pool is None:
        raise HTTPException(status_code=503, detail="Job queue unavailable")
    job = await pool.enqueue_job("run_inbox_sync_for_all_users", _job_id="internal:inbox-sync:run")
    logger.info("internal.inbox_sync_triggered", job_id=job.job_id if job else None)
    return {"queued": job is not None}


def _check_cron(authorization: str | None) -> None:
    """Vercel Cron authenticates with CRON_SECRET; the n8n token is accepted too, so the same
    daily run can be triggered by hand. Both compared in constant time."""
    settings = get_settings()
    candidates = [
        settings.cron_secret.get_secret_value(),
        settings.internal_webhook_token.get_secret_value(),
    ]
    if not any(c and hmac.compare_digest(authorization or "", f"Bearer {c}") for c in candidates):
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret")


@router.get("/cron/daily", summary="Daily run: discovery, inbox sync, digest (Vercel Cron)")
async def cron_daily(authorization: str | None = Header(default=None)) -> dict:
    """Runs inline — there is no queue on the serverless deployment. Each stage has its own
    time budget so the whole run stays inside the function's ceiling."""
    _check_cron(authorization)
    from app.services.digest import run_daily

    return await run_daily()
