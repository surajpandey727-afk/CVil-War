"""One-off backfill: re-run the sponsorship classifier against already-discovered jobs.

Every job in the DB was classified once, at discovery time, via
``core.sponsorship.classify.classify()``. Jobs discovered before the register's read-only
``/tmp`` path crash was fixed (see ``core/sponsorship/register.py``) were classified against
an empty register, so anything that should have matched CONFIRMED_REGISTER got silently
stamped UNKNOWN instead and stays that way forever -- job rows are never re-classified on
their own. This re-runs classify() for every UNKNOWN job now that the register is populated,
updating sponsor_confidence/sponsor_evidence in place. Safe to re-run: UNKNOWN-only jobs are
the only ones touched, and a job that still doesn't match just gets re-stamped UNKNOWN again.

Usage: DATABASE_URL=<prod-url> python scripts/reclassify_sponsors.py
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.sponsorship import register
from app.core.sponsorship.classify import classify
from app.models.enums import SponsorConfidence
from app.models.job import Job


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    row_count = await register.refresh()
    print(f"Register loaded: {row_count} rows")

    async with session_factory() as db:
        result = await db.execute(
            select(Job.id, Job.company, Job.description).where(
                Job.sponsor_confidence == SponsorConfidence.UNKNOWN
            )
        )
        rows = result.all()
        print(f"Jobs currently UNKNOWN: {len(rows)}")

        changed = 0
        for job_id, company, description in rows:
            confidence, evidence = classify(company, description or "")
            if confidence != SponsorConfidence.UNKNOWN:
                await db.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(sponsor_confidence=confidence, sponsor_evidence=evidence)
                )
                changed += 1
        await db.commit()
        print(f"Reclassified: {changed} jobs now have a non-UNKNOWN sponsor_confidence")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
