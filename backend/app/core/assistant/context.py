"""Per-request context every Assistant tool runs in, plus small shared helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ApplyMode
from app.models.job import Job
from app.models.user_settings import UserSettings

#: Cap on any single tool result fed back to the model.
MAX_RESULT_CHARS = 9000


@dataclass
class ToolContext:
    """Everything a tool may touch. ``db`` is the request's tenant-scoped session, so every
    ORM SELECT is already filtered to ``user_id`` — tools never open their own sessions."""

    db: AsyncSession
    user_id: str
    redis: Any | None = None
    pool: Any | None = None


def dumps(data: Any) -> str:
    """Compact JSON for a tool_result, truncated so one tool can't flood the context."""
    text = json.dumps(data, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '..."(truncated)"'
    return text


def pct(score: float | None) -> str | None:
    return None if score is None else f"{round(score * 100)}%"


def job_brief(job: Any) -> dict[str, Any]:
    """The compact job shape every list tool returns (works for ORM rows and schemas)."""
    sponsor = getattr(job, "sponsor_confidence", None)
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "workplace": getattr(job, "workplace_type", None),
        "salary": getattr(job, "salary_range", None),
        "match_score": job.match_score,
        "sponsor": getattr(sponsor, "value", sponsor),
        "status": getattr(job.status, "value", job.status),
    }


async def user_settings(db: AsyncSession, user_id: str) -> UserSettings | None:
    return (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()


def apply_mode_of(row: UserSettings | None) -> ApplyMode:
    """The user's apply mode, read the same way the system-status widget reads it."""
    automation = (row.automation if row else {}) or {}
    raw = str(
        automation.get("mode") or automation.get("apply_mode") or (row.apply_mode if row else "")
    )
    try:
        return ApplyMode(raw)
    except ValueError:
        return ApplyMode.REVIEW


def active_role_titles(row: UserSettings | None) -> list[str]:
    if row is None or not row.role_targets:
        return []
    return [
        str(rt.get("title", "")).strip()
        for rt in row.role_targets
        if isinstance(rt, dict) and rt.get("active", True) and str(rt.get("title", "")).strip()
    ]


async def owned_job(db: AsyncSession, user_id: str, job_id: str) -> Job | None:
    """Explicitly user-scoped job lookup (path-style ids are attacker-reachable input)."""
    return (
        await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    ).scalar_one_or_none()


def is_uk(job: Job) -> bool:
    """The UK-only policy verdict for one job, classifying it first if it never was."""
    if job.location_verified_at is None:
        from app.services.job_location import verdict_for

        return verdict_for(job).uk_eligible
    return bool(job.uk_eligible)
