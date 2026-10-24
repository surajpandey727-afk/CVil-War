"""Backfill / re-derive the normalised location fields on every stored job.

    cd backend && PYTHONPATH=$(pwd) python ../scripts/reclassify_locations.py [--dry-run]

Reads ``DATABASE_URL`` from the environment (never printed). Safe by construction:

* it only writes the derived columns (country/city/region/workplace/status/evidence/
  ``uk_eligible``) — the raw ``location`` text, which they are derived from, is never touched;
* it deletes nothing: a non-UK job stays in the table with ``uk_eligible = false``;
* it is idempotent: running it twice yields the same rows, so it can be re-run after any
  gazetteer change.

``--dry-run`` reports what would change and rolls back.

Runs across every tenant, so it bypasses the per-request tenant filter deliberately and only
for the job table it owns.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def main(dry_run: bool) -> None:
    from app.services.job_location import reclassify_all

    url = os.environ["DATABASE_URL"]
    connect_args = {"statement_cache_size": 0} if url.startswith("postgresql+asyncpg") else {}
    engine = create_async_engine(url, connect_args=connect_args)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        tally = await reclassify_all(db, dry_run=dry_run)
    await engine.dispose()
    mode = "DRY RUN (rolled back)" if dry_run else "applied"
    print(f"reclassify_locations: {mode}")
    for key in sorted(tally):
        print(f"  {key}: {tally[key]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(main(parser.parse_args().dry_run))
