"""Async SQLAlchemy engine and session factory."""

import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config.settings import get_settings

_settings = get_settings()

#: True when this process is a serverless function rather than a long-lived server.
#: A connection pool is an optimisation for a process that stays alive between requests. A
#: serverless function is frozen the moment it responds and may be thawed minutes later or
#: never, so a pooled socket is either dead on arrival or a connection held against the
#: database's limit by a process that will never use it again. NullPool opens per request and
#: closes on release, which is the correct trade there.
SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

_engine_options: dict[str, Any] = {
    "echo": _settings.environment.value == "development",
}
if SERVERLESS:
    _engine_options["poolclass"] = NullPool
    if _settings.database_url.startswith("postgresql+asyncpg"):
        # Serverless reaches Postgres through a transaction-mode pooler (Supavisor/PgBouncer),
        # because the direct Supabase host resolves to IPv6 only and serverless functions are
        # IPv4-only. In transaction mode a connection is handed to a different client between
        # statements, so a server-side prepared statement created on one checkout is gone —
        # or worse, collides by name — on the next. asyncpg prepares by default, so the cache
        # has to be switched off for this topology.
        _engine_options["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        }
else:
    # pre_ping costs a round trip per checkout; it earns that back on a long-lived pool whose
    # connections can be closed server-side between uses. With NullPool the connection is new
    # every time, so there is nothing stale to detect.
    _engine_options["pool_pre_ping"] = True

engine = create_async_engine(_settings.database_url, **_engine_options)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session with automatic cleanup.

    Usage as a FastAPI dependency:
        async def my_route(db: AsyncSession = Depends(get_db)): ...
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
