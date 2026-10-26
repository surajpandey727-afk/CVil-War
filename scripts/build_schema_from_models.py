"""Create the schema from the SQLAlchemy models, then stamp the Alembic version.

Why not `alembic upgrade head`? The historical migrations were written and only ever run
against SQLite (the dev/test default), where enums degrade to VARCHAR and unquoted defaults are
tolerated. On a fresh PostgreSQL they fail — batch add_column does not auto-create the enum
type, and several server defaults are unquoted enum/text literals that Postgres reads as column
references. The models are the authoritative current schema and exactly what the running app's
ORM expects, and SQLAlchemy's ``create_all`` emits correct Postgres DDL for them. We build from
those, then stamp ``alembic_version`` to head so future ``alembic upgrade head`` runs behave.

Run with DATABASE_URL pointing at the new project's SESSION-mode pooler (port 5432):
    python scripts/build_schema_from_models.py
"""

from __future__ import annotations

import asyncio
import os

def _alembic_head() -> str:
    """The single head of the migration chain, read from the migrations themselves.

    This used to be a hard-coded string that had already drifted one revision behind (it
    missed the notifications table), so a database built here and then upgraded tried to
    create that table twice and failed.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).resolve().parents[1] / "backend"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "app" / "db" / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise SystemExit(f"Expected one Alembic head, found {heads}")
    return heads[0]


HEAD_REVISION = _alembic_head()


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    # Import the app's metadata (all models register on Base.metadata via app.models).
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.models import Base

    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Record the migration version this schema corresponds to.
            await conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await conn.execute(text("DELETE FROM alembic_version"))
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": HEAD_REVISION}
            )
        async with engine.connect() as conn:
            n = (
                await conn.execute(
                    text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
                )
            ).scalar()
            enums = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                        "WHERE n.nspname='public' AND t.typtype='e'"
                    )
                )
            ).scalar()
        print(f"schema built: {n} public tables, {enums} enum types, stamped at {HEAD_REVISION}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
