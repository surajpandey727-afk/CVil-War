"""The connection-status endpoint the in-app widget polls: one honest view of every dependency."""

from __future__ import annotations

from unittest.mock import patch


API = "/api/v1/system"


class _Catalogue:
    def __init__(self, reachable: bool, error: str = "") -> None:
        self.reachable = reachable
        self.error = error


class TestSystemStatus:
    async def test_reports_every_dependency_with_an_action_for_the_pending_ones(self, client):
        async def _reachable():
            return _Catalogue(True)

        # discover() is imported inside _llm_state, so patch it at its definition.
        with patch("app.core.llm.discovery.discover", _reachable):
            resp = await client.get(f"{API}/status")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        keys = {s["key"] for s in body["services"]}
        assert {"llm", "gmail", "job_boards", "ai_agent", "database"} <= keys
        by_key = {s["key"]: s for s in body["services"]}
        # A fresh test user has connected nothing: gmail + job boards are pending with an action.
        assert by_key["gmail"]["status"] in ("pending", "not_configured")
        assert by_key["job_boards"]["status"] == "pending"
        assert by_key["job_boards"]["action_label"] == "Connect"
        assert by_key["llm"]["status"] == "connected"
        assert body["attention"] >= 1 and body["all_ok"] is False

    async def test_a_down_gateway_is_reported_not_raised(self, client):
        async def _down():
            raise TimeoutError("gateway slow")

        with patch("app.core.llm.discovery.discover", _down):
            resp = await client.get(f"{API}/status")

        assert resp.status_code == 200
        llm = next(s for s in resp.json()["services"] if s["key"] == "llm")
        assert llm["status"] == "unavailable"

    async def test_requires_auth(self, anon_client):
        resp = await anon_client.get(f"{API}/status")
        assert resp.status_code in (401, 403)
