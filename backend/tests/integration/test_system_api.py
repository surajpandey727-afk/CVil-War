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


    async def test_reports_email_delivery_readiness(self, client):
        """The owner's "why have I never received an email" must be answerable here. With the
        default log provider, email delivery is reported as not actually sending, with the
        concrete thing to enable."""
        resp = await client.get(f"{API}/status")
        by_key = {s["key"]: s for s in resp.json()["services"]}
        assert "email" in by_key, "email delivery state must be surfaced"
        email = by_key["email"]
        assert email["status"] in ("pending", "not_configured", "connected")
        # Default (log provider) must say plainly that nothing is delivered and how to fix it.
        assert "not delivered" in email["detail"].lower() or email["status"] == "connected"

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


class TestStatusIsActionable:
    async def test_review_mode_is_a_choice_not_something_to_connect(self, client, db_session):
        """The agent row read an `automation.mode` key nothing writes, so it was "pending"
        forever and the pill could never say "All connected"."""
        from app.models.user_settings import UserSettings
        from tests.conftest import TEST_USER_ID

        db_session.add(UserSettings(user_id=TEST_USER_ID, apply_mode="autonomous"))
        await db_session.commit()
        by_key = {s["key"]: s for s in (await client.get(f"{API}/status")).json()["services"]}
        assert by_key["ai_agent"]["status"] == "connected"
        assert "Autonomous" in by_key["ai_agent"]["detail"]

    async def test_server_email_is_informational_and_not_counted(self, client):
        body = (await client.get(f"{API}/status")).json()
        email = next(s for s in body["services"] if s["key"] == "email")
        assert email["optional"] is True
        assert email["action_path"] == ""  # there is nothing in the app that could fix it
        counted = [
            s for s in body["services"]
            if not s["optional"] and s["status"] in ("pending", "unavailable", "not_configured")
        ]
        assert body["attention"] == len(counted)

    async def test_job_board_connect_goes_to_the_platform_section(self, client):
        by_key = {s["key"]: s for s in (await client.get(f"{API}/status")).json()["services"]}
        assert by_key["job_boards"]["action_path"] == "/settings?section=platforms"
