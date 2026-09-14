"""Periodic job-discovery fan-out — the scheduler that was missing entirely.

Before this module, nothing polled any source in the background: ``services.job_search``
only ran when a user hit ``GET/POST /api/v1/jobs`` from the UI. That is the whole of the "no
new jobs are coming up" complaint — the search machinery worked, but nothing ever called it
unattended. ``run_discovery_for_all_users`` is the Arq cron entry point that does that calling,
once per configured interval, for every active user, reusing ``services.job_search.search_jobs``
exactly as the UI does (same dedup, same zero-cost-mode guard, same platform registry).
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_discovery.source_registry import usable_keys
from app.core.orchestration.recorder import record_agent_run
from app.db.session import async_session_factory
from app.db.tenant import current_user_id
from app.models.enums import AgentName
from app.models.user import User
from app.models.user_settings import UserSettings
from app.schemas.job import JobSearchRequest
from app.services.job_search import search_jobs

logger = structlog.get_logger(__name__)

#: Fan-out cap per user per cycle. An operator with many active role targets would otherwise
#: turn one cron tick into an unbounded number of platform searches.
MAX_QUERIES_PER_USER = 5


def _queries_for(settings: UserSettings | None) -> list[str]:
    """Search queries to run for one user this cycle.

    Uses the operator's own active role targets — their actual stated criteria — rather than
    a made-up default query, which would just add search noise nobody asked for. A user with
    no role targets configured yet gets no automatic discovery; on-demand search still works.
    """
    if settings is None or not settings.role_targets:
        return []
    titles = [
        title
        for rt in settings.role_targets
        if isinstance(rt, dict)
        and rt.get("active", True)
        and (title := str(rt.get("title", "")).strip())
    ]
    return titles[:MAX_QUERIES_PER_USER]


async def _discover_for_user(db: AsyncSession, user_id: str) -> int:
    """Run one discovery cycle for one user. Returns the number of jobs the search found.

    Assumes ``current_user_id`` is already scoped to ``user_id`` by the caller.
    """
    settings = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()

    queries = _queries_for(settings)
    if not queries:
        return 0

    # `None` (not a hand-maintained constant) so an unconfigured user gets every source
    # `usable_keys` currently considers live, not whatever a fixed list said when it was
    # last edited — see the matching comment in `services.job_search.search_jobs`.
    requested_platforms = (
        settings.platforms_enabled if settings and settings.platforms_enabled else None
    )
    platforms = usable_keys(requested_platforms)
    if not platforms:
        logger.info("discovery.no_usable_platforms", user_id=user_id)
        return 0

    found = 0
    for query in queries:
        try:
            response = await search_jobs(
                db, JobSearchRequest(query=query, platforms=platforms, limit=25), user_id,
            )
            found += response.total
        except Exception as exc:
            # One bad query (a malformed title, a transient adapter error) must not stop the
            # rest of this user's targets, or the whole cycle for every other user.
            logger.warning(
                "discovery.query_failed", user_id=user_id, query=query, error=str(exc),
            )
    return found


async def run_discovery_for_all_users(ctx: dict[str, Any]) -> None:
    """Scheduled (Arq cron): poll every active user's enabled sources for new listings.

    Each user's discovery run is scoped via the tenant contextvar for its duration then
    reset, mirroring ``workers.tasks._apply`` — one user's queries must never leak into
    another's tenant-scoped reads (``search_jobs``'s own-jobs dedup lookup, in particular).
    """
    redis = ctx.get("redis")
    async with async_session_factory() as db:
        user_ids = (
            await db.execute(
                select(User.id).where(User.is_active.is_(True), User.deleted_at.is_(None))
            )
        ).scalars().all()

        total_found = 0
        for user_id in user_ids:
            token = current_user_id.set(user_id)
            try:
                async with record_agent_run(
                    db, user_id, AgentName.DISCOVERY,
                    input_summary="Poll enabled sources against active role targets",
                    linked_entity_type="user", linked_entity_id=user_id, redis=redis,
                ) as run:
                    found = await _discover_for_user(db, user_id)
                    run.output_summary = f"{found} job(s) found"
                total_found += found
            except Exception as exc:
                logger.error("discovery.user_run_failed", user_id=user_id, error=str(exc))
            finally:
                current_user_id.reset(token)

    logger.info("discovery.cycle_complete", users=len(user_ids), jobs_found=total_found)
