"""Arq Redis pool lifecycle + accessor. The apply producer lands in Phase 1."""

from __future__ import annotations

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config.settings import get_settings

logger = structlog.get_logger(__name__)

_pool: ArqRedis | None = None


async def init_arq_pool() -> None:
    """Create the Arq pool at startup. Degrades gracefully if Redis is unavailable."""
    global _pool
    try:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        logger.info("arq_pool_ready")
    except Exception as exc:
        _pool = None
        logger.warning("arq_pool_unavailable", error=str(exc))


def get_arq_pool() -> ArqRedis | None:
    """Return the Arq pool, or ``None`` if it could not be created."""
    return _pool


async def close_arq_pool() -> None:
    """Dispose the Arq pool at shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
