"""Integration tests for the internal webhook targets (n8n): shared-secret auth, not JWT."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import internal as internal_module
from app.db.arq import get_arq_pool

API_PREFIX = "/api/v1/internal"


def _fake_settings(token: str) -> SimpleNamespace:
    return SimpleNamespace(internal_webhook_token=SimpleNamespace(get_secret_value=lambda: token))


@pytest.fixture
async def internal_client(monkeypatch):
    """A client with ``get_arq_pool`` overridden via FastAPI's own dependency-override
    mechanism — ``Depends(get_arq_pool)`` binds the function object at import time, so
    monkeypatching ``internal_module.get_arq_pool`` afterward does not reach it; only
    ``app.dependency_overrides`` does."""
    from app.main import create_app

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=SimpleNamespace(job_id="j1")))
    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_arq_pool] = lambda: pool

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, pool
    app.dependency_overrides.clear()


class TestInternalAuth:
    async def test_missing_header_is_rejected(self, anon_client) -> None:
        with patch.object(internal_module, "get_settings", lambda: _fake_settings("secret")):
            response = await anon_client.post(f"{API_PREFIX}/discovery/run")
        assert response.status_code == 401

    async def test_wrong_token_is_rejected(self, anon_client) -> None:
        with patch.object(internal_module, "get_settings", lambda: _fake_settings("secret")):
            response = await anon_client.post(
                f"{API_PREFIX}/discovery/run",
                headers={"Authorization": "Bearer wrong"},
            )
        assert response.status_code == 401

    async def test_unset_token_rejects_everything(self, anon_client) -> None:
        """Fail-closed: no configured token means the endpoint refuses even a matching
        (empty) header rather than treating an unset secret as 'open'."""
        with patch.object(internal_module, "get_settings", lambda: _fake_settings("")):
            response = await anon_client.post(
                f"{API_PREFIX}/discovery/run", headers={"Authorization": "Bearer "},
            )
        assert response.status_code == 401

    async def test_correct_token_enqueues_discovery(self, internal_client) -> None:
        client, pool = internal_client
        with patch.object(internal_module, "get_settings", lambda: _fake_settings("secret")):
            response = await client.post(
                f"{API_PREFIX}/discovery/run", headers={"Authorization": "Bearer secret"},
            )
        assert response.status_code == 200
        assert response.json() == {"queued": True}
        pool.enqueue_job.assert_awaited_once_with(
            "run_discovery_for_all_users", _job_id="internal:discovery:run"
        )

    async def test_correct_token_enqueues_inbox_sync(self, internal_client) -> None:
        client, pool = internal_client
        with patch.object(internal_module, "get_settings", lambda: _fake_settings("secret")):
            response = await client.post(
                f"{API_PREFIX}/inbox-sync/run", headers={"Authorization": "Bearer secret"},
            )
        assert response.status_code == 200
        assert response.json() == {"queued": True}
        pool.enqueue_job.assert_awaited_once_with(
            "run_inbox_sync_for_all_users", _job_id="internal:inbox-sync:run"
        )

    async def test_queue_unavailable_returns_503(self, anon_client) -> None:
        with patch.object(
            internal_module, "get_settings", lambda: _fake_settings("secret")
        ):
            response = await anon_client.post(
                f"{API_PREFIX}/discovery/run", headers={"Authorization": "Bearer secret"},
            )
        assert response.status_code == 503
