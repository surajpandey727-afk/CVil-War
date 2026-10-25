"""Database-as-queue worker: lets a long-running machine apply for a serverless API (D-016).

The production API runs on Vercel, which has no Redis, no worker and no browser. Approving an
application there used to run the whole apply pipeline *inside the HTTP request*. With
``APPLY_DISPATCH=db_queue`` the API instead leaves the row at ``approved`` / ``queued``, and
this worker — run on any always-on machine with a browser — picks those rows up straight from
the database and runs the same ``run_apply_pipeline`` the arq worker runs.

Why the database and not a hosted Redis: the rows already *are* the queue (their status is the
state machine), so there is nothing to keep in sync, nothing to lose if the worker is off for a
week, and no second free-tier service whose command quota an arq poll loop would exhaust. See
docs/LOCAL_SETUP.md for the decision record.

Concurrency: each claim takes a Postgres transaction-independent advisory lock keyed on the
application id, so two workers never run the same application at once; the pipeline's own
``APPLIED`` check makes a late duplicate a no-op. On SQLite (single local process) the lock is
a no-op.

    python -m app.workers.db_queue --dry-run          # list what would run; writes nothing
    python -m app.workers.db_queue --once             # one pass, then exit
    python -m app.workers.db_queue                    # poll forever
    python scripts/db_worker.py --prod ...            # use PROD_DATABASE_URL instead
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import zlib
from dataclasses import dataclass, field
from typing import Any

#: Statuses the API leaves for a worker: ``queued`` (autonomous mode, or a policy hold) and
#: ``approved`` (a human approved it in review/batch mode).
CLAIMABLE = ("queued", "approved")


@dataclass
class WorkerState:
    """In-process memory of rows that were run but are still claimable (a policy HOLD puts
    the row back to ``queued``). Without it the worker would re-run a held row every poll."""

    backoff_seconds: float = 900.0
    _skip_until: dict[str, float] = field(default_factory=dict)

    def skipping(self, app_id: str, now: float) -> bool:
        return self._skip_until.get(app_id, 0.0) > now

    def back_off(self, app_id: str, now: float) -> None:
        self._skip_until[app_id] = now + self.backoff_seconds


def _lock_key(app_id: str) -> int:
    """Stable signed 32-bit advisory-lock key for an application id."""
    return zlib.crc32(f"cvilwar-apply:{app_id}".encode()) - 2**31


async def claimable_ids(db: Any, *, user_id: str | None = None, limit: int = 20) -> list[str]:
    """Ids of applications waiting for a worker, oldest first. Unscoped: the worker serves
    every tenant, so the caller must not have a tenant set."""
    from sqlalchemy import select

    from app.models.application import Application

    stmt = (
        select(Application.id)
        .where(Application.status.in_(CLAIMABLE))
        .order_by(Application.updated_at.asc())
        .limit(limit)
    )
    if user_id:
        stmt = stmt.where(Application.user_id == user_id)
    return list((await db.execute(stmt)).scalars().all())


async def _try_lock(conn: Any, app_id: str) -> bool:
    from sqlalchemy import text

    if conn.dialect.name != "postgresql":
        return True
    got = await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _lock_key(app_id)})
    return bool(got.scalar())


async def _unlock(conn: Any, app_id: str) -> None:
    from sqlalchemy import text

    if conn.dialect.name == "postgresql":
        await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_key(app_id)})


async def run_connects(*, dry_run: bool = False) -> list[dict[str, str]]:
    """Open a sign-in window here for each platform the web app asked to connect.

    Production has no browser, so a Connect click there is queued for this machine; see
    ``services.platform_session``. Each capture is headed — the person signs in themselves on
    this desktop — and runs one at a time, because each needs that person's attention.
    """
    import structlog

    from app.core.automation.connect import claim_connect, run_queued_connect
    from app.db.session import async_session_factory
    from app.services.platform_session import pending_connects

    log = structlog.get_logger(__name__)
    results: list[dict[str, str]] = []
    async with async_session_factory() as db:
        pending = [(r.id, r.user_id, r.platform) for r in await pending_connects(db)]
    for row_id, owner, platform in pending:
        if dry_run:
            results.append({"id": row_id, "outcome": f"would_open_sign_in:{platform}"})
            continue
        async with async_session_factory() as db:
            if not await claim_connect(db, row_id):
                continue  # another host took it, or it was cancelled
        outcome = await run_queued_connect(row_id, owner, platform)
        results.append({"id": row_id, "outcome": f"sign_in_{outcome.value}:{platform}"})
        log.info("db_queue.connect", platform=platform, outcome=outcome.value)
    return results


async def run_once(
    *,
    state: WorkerState,
    dry_run: bool = False,
    user_id: str | None = None,
    limit: int = 20,
    connect_only: bool = False,
) -> list[dict[str, str]]:
    """One pass over the queue. Returns what happened to each row (for logs and tests)."""
    import structlog

    from app.db.session import async_session_factory, engine
    from app.db.tenant import current_user_id
    from app.models.application import Application
    from app.workers.tasks import run_apply_pipeline

    log = structlog.get_logger(__name__)
    token = current_user_id.set(None)
    results: list[dict[str, str]] = []
    try:
        results.extend(await run_connects(dry_run=dry_run))
        if connect_only:
            return results
        async with async_session_factory() as db:
            ids = await claimable_ids(db, user_id=user_id, limit=limit)
        now = time.monotonic()
        for app_id in ids:
            if state.skipping(app_id, now):
                continue
            if dry_run:
                results.append({"id": app_id, "outcome": "would_run"})
                continue
            async with engine.connect() as lock_conn:
                if not await _try_lock(lock_conn, app_id):
                    results.append({"id": app_id, "outcome": "locked_by_another_worker"})
                    continue
                try:
                    await run_apply_pipeline({"job_try": 1, "redis": None}, app_id)
                finally:
                    await _unlock(lock_conn, app_id)
            async with async_session_factory() as db:
                app = await db.get(Application, app_id)
                status = str(app.status) if app else "missing"
            if status in CLAIMABLE:
                state.back_off(app_id, time.monotonic())
            results.append({"id": app_id, "outcome": status})
            log.info("db_queue.processed", application_id=app_id, status=status)
    finally:
        current_user_id.reset(token)
    return results


async def run_forever(*, poll_seconds: float, state: WorkerState, **kw: Any) -> None:
    import structlog

    log = structlog.get_logger(__name__)
    log.info("db_queue.started", poll_seconds=poll_seconds)
    while True:
        try:
            done = await run_once(state=state, **kw)
            if done:
                log.info("db_queue.pass", processed=len(done))
        except Exception as exc:  # a bad pass must not kill a long-running worker
            log.error("db_queue.pass_failed", error=type(exc).__name__, detail=str(exc)[:300])
        await asyncio.sleep(poll_seconds)


def _parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m app.workers.db_queue")
    p.add_argument("--prod", action="store_true", help="use PROD_DATABASE_URL (launcher only)")
    p.add_argument("--once", action="store_true", help="one pass, then exit")
    p.add_argument("--dry-run", action="store_true", help="list claimable rows; write nothing")
    p.add_argument("--user-id", default=None, help="only this user's applications")
    p.add_argument("--poll", type=float, default=30.0, help="seconds between passes")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument(
        "--connect-only",
        action="store_true",
        help="only open queued platform sign-ins; never touch applications",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    if args.prod:
        url = os.environ.get("PROD_DATABASE_URL", "").strip()
        if not url:
            print("BLOCKED: --prod needs PROD_DATABASE_URL in the environment.")
            return 2
        # The engine is built from DATABASE_URL when app.db.session is first imported, which
        # importing this package already did. Refuse rather than silently run against
        # whatever database that was; scripts/db_worker.py swaps the URL before any import.
        if os.environ.get("DATABASE_URL") != url:
            print("Use `python scripts/db_worker.py --prod ...` (it sets the URL before import).")
            return 2
    state = WorkerState()
    kw = {
        "dry_run": args.dry_run,
        "user_id": args.user_id,
        "limit": args.limit,
        "connect_only": args.connect_only,
    }
    if args.once or args.dry_run:
        results = asyncio.run(run_once(state=state, **kw))
        for r in results:
            print(f"{r['id']}  {r['outcome']}")
        print(f"{len(results)} item(s) {'claimable' if args.dry_run else 'processed'}")
        return 0
    asyncio.run(run_forever(poll_seconds=args.poll, state=state, **kw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
