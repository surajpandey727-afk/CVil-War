"""Apply the UK location policy to stored jobs.

The classifier (:mod:`app.core.geo.classify`) is pure; this module writes its verdict onto
``Job`` rows. Three callers:

* discovery, for every new listing (``stamp``), so a job is classified before it is stored;
* the jobs list, which calls ``classify_pending`` first so any row stored before the policy
  existed — or by a code path that skipped ``stamp`` — is classified before it can be shown;
* ``scripts/reclassify_locations.py``, the explicit, re-runnable backfill.

Nothing here deletes a job. A non-UK row stays in the table with ``uk_eligible = false``; it is
simply never listed. That keeps the backfill reversible and the audit trail intact.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import LocationVerdict, classify_location
from app.models.job import Job
from app.schemas.job import LocationSummary

logger = structlog.get_logger(__name__)

#: Upper bound on rows classified in one call, so a list request on a huge backlog stays
#: bounded; the remainder is picked up by the next call.
_PENDING_BATCH = 2000


def verdict_for(job: Job) -> LocationVerdict:
    return classify_location(
        job.location or "",
        remote=bool(job.remote),
        platform=job.platform or "",
        title=job.title or "",
    )


def stamp(job: Job, verdict: LocationVerdict | None = None, *, now: datetime | None = None) -> Job:
    """Write a verdict onto a job (computing it if not supplied). Returns the job."""
    v = verdict or verdict_for(job)
    job.country_code = v.country_code
    job.country_name = v.country_name
    job.city = v.city
    job.region = v.region
    job.workplace_type = v.workplace_type
    job.remote_eligible_countries = list(v.remote_eligible_countries) or None
    job.location_verification_status = v.status
    job.location_evidence_source = v.evidence
    job.location_verified_at = now or datetime.now(UTC)
    job.uk_eligible = v.uk_eligible
    return job


async def classify_pending(db: AsyncSession) -> int:
    """Classify every not-yet-classified job visible to the current tenant. Returns the count."""
    rows = (
        (
            await db.execute(
                select(Job).where(Job.location_verification_status.is_(None)).limit(_PENDING_BATCH)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    now = datetime.now(UTC)
    for job in rows:
        stamp(job, now=now)
    await db.commit()
    logger.info(
        "job_location.classified_pending",
        rows=len(rows),
        uk_eligible=sum(1 for j in rows if j.uk_eligible),
    )
    return len(rows)


async def reclassify_all(db: AsyncSession, *, dry_run: bool = False) -> dict[str, int]:
    """Re-derive every row's location fields (after a gazetteer change). Returns a tally."""
    rows = (await db.execute(select(Job))).scalars().all()
    tally: dict[str, int] = {"rows": len(rows), "uk_eligible": 0, "changed": 0}
    now = datetime.now(UTC)
    for job in rows:
        v = verdict_for(job)
        key = f"status:{v.status}"
        tally[key] = tally.get(key, 0) + 1
        tally["uk_eligible"] += int(v.uk_eligible)
        if (job.uk_eligible, job.location_verification_status, job.city) != (
            v.uk_eligible,
            v.status,
            v.city,
        ):
            tally["changed"] += 1
        if not dry_run:
            stamp(job, v, now=now)
    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return tally


async def summary(db: AsyncSession) -> LocationSummary:
    """Tally the current tenant's jobs by location outcome (classifying stragglers first)."""
    await classify_pending(db)
    rows = (
        await db.execute(
            select(Job.uk_eligible, Job.location_verification_status, func.count(Job.id)).group_by(
                Job.uk_eligible, Job.location_verification_status
            )
        )
    ).all()
    out = LocationSummary()
    for eligible, status, count in rows:
        out.total += count
        if eligible:
            out.uk_eligible += count
        elif status == "verified":
            out.outside_uk += count
        else:
            out.quarantined += count
    return out
