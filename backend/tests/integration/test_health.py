"""Integration tests for the health check endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

from app.config.constants import APP_VERSION
from app.core.llm.discovery import Catalogue


@pytest.fixture(autouse=True)
def _fast_llm_gateway_check():
    """Every test here hits the real `/health` route, which calls the LLM-gateway
    discovery check. Mocked so the suite exercises real routing/response-shape logic
    without depending on a real gateway being reachable (slow and flaky in CI either way —
    /health's own 2s timeout bounds the worst case in production, but there is no reason
    for every test run to pay it)."""
    fake = Catalogue(reachable=True, error=None, fetched_at=0.0)
    with patch(
        "app.core.llm.discovery.discover", new=AsyncMock(return_value=fake),
    ):
        yield fake


class TestHealthEndpoint:
    """Tests for GET /health."""

    async def test_health_returns_ok(self, client):
        response = await client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["version"] == APP_VERSION

    async def test_security_headers_are_present(self, client):
        response = await client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "Referrer-Policy" in response.headers

    async def test_health_reports_dependency_status(self, client):
        # /health is a real readiness probe: DB is connected in the test harness, so db is True.
        response = await client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["db"] is True
        assert "redis" in body

    async def test_health_reports_llm_gateway_status(self, client):
        """Pins a real gap: /health checked only DB and Redis, with no way to distinguish
        "the app is up" from "the app is up but its LLM gateway is unreachable"."""
        response = await client.get("/health")
        assert response.json()["llm_gateway"] == {"reachable": True, "error": None}

    async def test_health_reports_a_slow_gateway_as_unreachable_rather_than_hanging(
        self, client,
    ):
        """A slow or hung gateway must not make the whole readiness probe slow — a container
        orchestrator reading a stalled /health as "unhealthy" would restart an otherwise
        working backend over a third party being slow."""
        import asyncio

        async def _never_returns(*, force: bool = False):
            await asyncio.sleep(30)

        with patch("app.core.llm.discovery.discover", new=_never_returns):
            response = await client.get("/health")

        assert response.status_code == 200  # a slow gateway is not a down database
        assert response.json()["llm_gateway"]["reachable"] is False

    async def test_health_reports_external_api_credential_presence(self, client):
        """Configured-or-not, not a live probe — see the endpoint's own docstring on why
        this must never itself depend on a third party's current uptime."""
        body = (await client.get("/health")).json()
        apis = body["external_apis"]
        assert set(apis) == {"reed", "adzuna", "exa", "gmail", "apollo"}
        assert all(isinstance(v, bool) for v in apis.values())

    async def test_health_returns_503_when_db_is_down(self, client, monkeypatch):
        # A dead database must surface as 503 so a healthcheck / uptime monitor can detect it.
        class _BoomConn:
            async def __aenter__(self):
                raise RuntimeError("db down")

            async def __aexit__(self, *a):
                return False

        class _FakeEngine:
            def connect(self):
                return _BoomConn()

        monkeypatch.setattr("app.db.session.engine", _FakeEngine())
        response = await client.get("/health")

        assert response.status_code == 503
        assert response.json()["db"] is False
