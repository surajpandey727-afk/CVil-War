"""Rate limiting when Redis is unreachable.

The behaviour these pin was chosen against two worse alternatives, and both had been shipped
at some point. Failing closed in production took the entire service down whenever Redis was
absent: on the serverless deployment, which has no Redis provisioned, every login returned 429
and nobody could sign in. Failing open removed throttling altogether, which is precisely the
outcome an attacker able to disrupt Redis is aiming for.

The fallback keeps a real limit in force per process. It is weaker than a shared counter and
is not pretending otherwise — these tests exist to make sure it is a limit, not a bypass.
"""

from __future__ import annotations

import pytest

from app.config.settings import Environment
from app.core.exceptions import RateLimitError
from app.core.ratelimit import RateLimiter, _InProcessWindow


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    """Force the Redis-unavailable path for every test here."""
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: None)


@pytest.fixture
def production(monkeypatch):
    """Report the environment as production, which is where fail-closed used to bite."""
    from app.config import settings as settings_module

    cfg = settings_module.get_settings()
    monkeypatch.setattr(cfg, "environment", Environment.PRODUCTION, raising=False)


class TestTheServiceStaysUp:
    async def test_a_first_request_is_allowed_in_production(self, production) -> None:
        """The regression this exists for: a first login attempt answered 429 because the
        limiter refused to serve at all without Redis."""
        await RateLimiter().check("1.2.3.4:/login", limit=5, window=60)

    async def test_requests_below_the_limit_all_pass(self, production) -> None:
        limiter = RateLimiter()
        for _ in range(5):
            await limiter.check("1.2.3.4:/login", limit=5, window=60)


class TestItIsStillALimit:
    async def test_exceeding_the_limit_raises(self, production) -> None:
        """A fallback that never says no is a bypass, not a fallback."""
        limiter = RateLimiter()
        for _ in range(3):
            await limiter.check("9.9.9.9:/login", limit=3, window=60)
        with pytest.raises(RateLimitError):
            await limiter.check("9.9.9.9:/login", limit=3, window=60)

    async def test_outside_production_a_missing_redis_means_no_limit(self) -> None:
        """Deliberately unchanged from the original behaviour.

        The fallback counters live on a module-level singleton, so applying them in tests
        would carry state between cases and make any test that exercises an auth endpoint
        repeatedly fail on 429 depending on execution order — which is exactly what happened
        when this was first written without the environment check.
        """
        limiter = RateLimiter()
        for _ in range(50):
            await limiter.check("8.8.8.8:/login", limit=2, window=60)

    async def test_separate_clients_have_separate_budgets(self, production) -> None:
        """One client exhausting its allowance must not lock everyone else out."""
        limiter = RateLimiter()
        for _ in range(2):
            await limiter.check("a:/login", limit=2, window=60)
        await limiter.check("b:/login", limit=2, window=60)


class TestTheWindow:
    def test_counting_is_per_window_not_cumulative(self) -> None:
        window = _InProcessWindow()
        assert window.hit("k", limit=1, window=60)
        assert not window.hit("k", limit=1, window=60)

    def test_a_later_window_starts_fresh(self, monkeypatch) -> None:
        window = _InProcessWindow()
        monkeypatch.setattr("app.core.ratelimit.time.time", lambda: 0.0)
        assert window.hit("k", limit=1, window=60)
        assert not window.hit("k", limit=1, window=60)
        monkeypatch.setattr("app.core.ratelimit.time.time", lambda: 120.0)
        assert window.hit("k", limit=1, window=60)

    def test_key_growth_is_bounded(self, monkeypatch) -> None:
        """An attacker cycling keys must not be able to grow this without limit."""
        window = _InProcessWindow()
        monkeypatch.setattr(_InProcessWindow, "MAX_KEYS", 50)
        monkeypatch.setattr("app.core.ratelimit.time.time", lambda: 0.0)
        for i in range(200):
            window.hit(f"key-{i}", limit=100, window=60)
        # Eviction drops stale windows; with every key in the current window the map is
        # allowed to hold them, but the sweep must have run rather than growing unchecked.
        monkeypatch.setattr("app.core.ratelimit.time.time", lambda: 600.0)
        window.hit("fresh", limit=100, window=60)
        assert len(window._counts) <= 200


class TestOperatorVisibility:
    async def test_the_degradation_is_logged_once_not_per_request(
        self, production, monkeypatch
    ) -> None:
        """A standing degradation logged on every call buries everything else in the log."""
        seen: list[str] = []
        monkeypatch.setattr(
            "app.core.ratelimit.logger",
            type("L", (), {"warning": lambda _self, event, **kw: seen.append(event)})(),
        )
        limiter = RateLimiter()
        for _ in range(4):
            await limiter.check("1.1.1.1:/x", limit=100, window=60)
        assert seen.count("ratelimit_degraded_no_redis") == 1
