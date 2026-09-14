"""Fixed-window rate limiting: Redis when it is available, in-process when it is not."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request

from app.config.settings import Environment, get_settings
from app.core.exceptions import RateLimitError
from app.db.redis import get_redis

logger = structlog.get_logger(__name__)


class _InProcessWindow:
    """Per-process fixed-window counter, used only when Redis is unreachable.

    This is a fallback, not a peer of the Redis limiter. Each process keeps its own counters,
    so with several instances serving one client the effective limit is the configured limit
    multiplied by the number of live instances. That is materially weaker than a shared
    counter and is the reason Redis stays the preferred path.

    It exists because the alternative was worse in both directions. Failing closed took the
    whole service down whenever Redis was absent — on a serverless deployment with no Redis
    provisioned, every single login returned 429 and the product was unusable. Failing open
    removed throttling altogether, which is exactly what an attacker who can knock Redis over
    would want. A per-process bound keeps a real limit in force while the service stays up.
    """

    #: Hard cap on distinct keys held, so an attacker cycling keys cannot grow this without
    #: limit. Eviction drops the oldest window wholesale rather than tracking LRU per key —
    #: this is a safety valve, not a cache.
    MAX_KEYS = 10_000

    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = defaultdict(int)
        self._lock = threading.Lock()

    def hit(self, key: str, *, limit: int, window: int) -> bool:
        """Record one request. Returns True when it is within the limit."""
        slot = int(time.time() // window)
        with self._lock:
            if len(self._counts) > self.MAX_KEYS:
                # Drop every window older than the current one; bounded and cheap.
                self._counts = defaultdict(
                    int, {k: v for k, v in self._counts.items() if k[1] >= slot}
                )
            self._counts[(key, slot)] += 1
            return self._counts[(key, slot)] <= limit


class RateLimiter:
    """Fixed-window counter, backed by Redis where possible."""

    def __init__(self) -> None:
        self._fallback = _InProcessWindow()
        self._warned = False

    async def check(self, key: str, *, limit: int, window: int) -> None:
        redis = get_redis()
        if redis is None:
            production = get_settings().environment == Environment.PRODUCTION
            if production and not self._warned:
                # Once per process: this is a standing degradation, not a per-request event,
                # and logging it on every call would bury everything else.
                self._warned = True
                logger.warning(
                    "ratelimit_degraded_no_redis",
                    detail=(
                        "Redis is unreachable; throttling is per-process only and therefore "
                        "weaker than configured. Provision REDIS_URL to restore shared limits."
                    ),
                )
            if not self._fallback.hit(key, limit=limit, window=window):
                raise RateLimitError("Too many requests")
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
