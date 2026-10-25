"""The daily run production otherwise lacks: discover, sync the inbox, email a digest.

Vercel runs no worker, no Redis and no scheduler, so "tell me about new jobs" never happened
unless the owner pressed Search (docs/ARCHITECTURE_AUDIT.md: "nothing scheduled runs in
production"). A Vercel Cron hits ``GET /api/v1/internal/cron/daily`` once a day; this module is
what it runs, each stage under its own time budget so one slow stage cannot starve the next or
run the function past its ceiling.

The digest is one email per user covering the last day's notifications that were not already
emailed individually — Dreamwork's "email you what went out ... as a daily summary".
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from app.db.session import async_session_factory
from app.db.tenant import current_user_id
from app.models.notification import Notification
from app.models.user import User

logger = structlog.get_logger(__name__)

#: Inside the API function's 300 s ceiling (backend/vercel.json), with headroom for the digest.
DISCOVERY_BUDGET_S = 200.0
INBOX_BUDGET_S = 40.0
#: Discovery stops starting new searches this long before its hard budget.
SOFT_STOP_MARGIN_S = 45.0
DIGEST_WINDOW = timedelta(hours=24)


async def run_daily(*, discovery_budget: float = DISCOVERY_BUDGET_S) -> dict[str, Any]:
    """Discovery → inbox sync → digest. Returns what each stage did (for the cron's log)."""
    from app.services.discovery_scheduler import run_discovery_for_all_users
    from app.services.inbox_sync import run_inbox_sync_for_all_users

    out: dict[str, Any] = {}
    for name, fn, budget in (
        ("discovery", run_discovery_for_all_users, discovery_budget),
        ("inbox_sync", run_inbox_sync_for_all_users, INBOX_BUDGET_S),
    ):
        # The soft deadline lets discovery finish its current search and stop cleanly; the
        # hard timeout below is only a backstop.
        ctx = {"redis": None, "deadline": time.monotonic() + max(0.0, budget - SOFT_STOP_MARGIN_S)}
        try:
            await asyncio.wait_for(fn(ctx), timeout=budget)
            out[name] = "ok"
        except TimeoutError:
            out[name] = f"stopped at {int(budget)}s budget"
        except Exception as exc:
            logger.error("daily.stage_failed", stage=name, error=type(exc).__name__)
            out[name] = f"failed ({type(exc).__name__})"
    out["digests_sent"] = await send_daily_digests()
    logger.info("daily.complete", **out)
    return out


async def send_daily_digests(now: datetime | None = None) -> int:
    """Email each user one summary of the day's notifications not already emailed."""
    from app.services.gmail_send import NotifyOutcome, send_notification_email

    now = now or datetime.now(UTC)
    sent = 0
    async with async_session_factory() as db:
        token = current_user_id.set(None)
        try:
            users = (
                (
                    await db.execute(
                        select(User.id).where(User.is_active.is_(True), User.deleted_at.is_(None))
                    )
                )
                .scalars()
                .all()
            )
        finally:
            current_user_id.reset(token)
        for user_id in users:
            token = current_user_id.set(user_id)
            try:
                rows = (
                    (
                        await db.execute(
                            select(Notification)
                            .where(
                                Notification.user_id == user_id,
                                Notification.created_at >= now - DIGEST_WINDOW,
                                Notification.emailed_at.is_(None),
                            )
                            .order_by(Notification.created_at.desc())
                            .limit(40)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not rows:
                    continue
                outcome = await send_notification_email(
                    db, user_id, subject=_subject(rows), body=_body(rows)
                )
                if outcome is NotifyOutcome.SENT:
                    for r in rows:
                        r.emailed_at = now
                    await db.commit()
                    sent += 1
            except Exception as exc:
                logger.warning("digest.user_failed", error=type(exc).__name__)
                await db.rollback()
            finally:
                current_user_id.reset(token)
    return sent


def _subject(rows: list[Notification]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.kind] = counts.get(r.kind, 0) + 1
    parts = []
    if counts.get("best_match"):
        parts.append(
            f"{counts['best_match']} strong match{'es' if counts['best_match'] > 1 else ''}"
        )
    applied = counts.get("application_submitted", 0)
    if applied:
        parts.append(f"{applied} application update{'s' if applied > 1 else ''}")
    needs = counts.get("action_required", 0) + counts.get("application_failed", 0)
    if needs:
        parts.append(f"{needs} need{'s' if needs == 1 else ''} you")
    return "CVil-War daily: " + (", ".join(parts) or f"{len(rows)} update(s)")


def _body(rows: list[Notification]) -> str:
    from app.services.notifications import _absolute

    lines = ["Here is what happened in CVil-War in the last 24 hours.", ""]
    for r in rows:
        lines.append(f"• {r.title}")
        if r.body:
            lines.append(f"  {r.body[:240]}")
        lines.append(f"  {_absolute(r.link)}")
    lines += ["", "Open the bell in CVil-War to see everything and mark it read."]
    return "\n".join(lines)
