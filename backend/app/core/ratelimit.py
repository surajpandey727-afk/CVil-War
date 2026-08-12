"""Redis fixed-window rate limiter + a FastAPI dependency factory."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request

from app.config.settings import Environment, get_settings
from app.core.exceptions import RateLimitError
from app.db.redis import get_redis


class RateLimiter:
    """Fixed-window counter in Redis. Fail-open in dev, fail-closed in production."""

    async def check(self, key: str, *, limit: int, window: int) -> None:
        redis = get_redis()
        if redis is None:
            if get_settings().environment == Environment.PRODUCTION:
                raise RateLimitError("Rate limiter unavailable")
            return
        bucket = f"ratelimit:{key}:{int(time.time() // window)}"
        count = await redis.incr(bucket)
        if count == 1:
            await redis.expire(bucket, window)
        if count > limit:
            raise RateLimitError("Too many requests")


_limiter = RateLimiter()


def rate_limit(limit: int, window: int) -> Callable[[Request], Awaitable[None]]:
    """Build a dependency that throttles by client IP + route path."""

    async def _dependency(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        await _limiter.check(f"{client}:{request.url.path}", limit=limit, window=window)

    return _dependency
