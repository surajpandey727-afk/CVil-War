"""Connect on the Settings page (Reed, Adzuna and the other login portals).

Every Connect click in production failed. Three separate causes, one test group each:

* the sign-in window was opened by the API process, and Vercel has no browser
  (``No module named 'playwright'``), so production now queues the request for the
  automation host on the owner's PC;
* a successful capture could never be saved: ``_persist`` imported a function that does not
  exist, and ``import_session`` left a first connection at ``not_connected``;
* Adzuna was offered a Connect button for a source whose credential is an API key, and the
  server rejected it with a 422.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import get_settings
from app.core.automation import connect
from app.core.automation.connect import ConnectAttempt, ConnectManager, ConnectState
from app.models.enums import SessionState
from app.models.platform_session import PlatformSession
from app.services import platform_session as service
from app.services import platforms as platform_service
from tests.conftest import TEST_USER_ID

API = "/api/v1/platform-sessions"
STATE = {
    "cookies": [{"name": "session", "value": "abc", "domain": ".reed.co.uk", "expires": -1}],
    "origins": [],
}


@pytest.fixture()
def queued(monkeypatch):
    """Production's dispatch: sign-ins run on the automation host, not in the API."""
    monkeypatch.setattr(get_settings(), "apply_dispatch", "db_queue")


@pytest.fixture()
def bound_factory(async_engine, monkeypatch):
    """Point the worker-side code at the test database."""
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "async_session_factory", factory)
    return factory


class TestQueuedConnectApi:
    async def test_production_connect_queues_instead_of_launching_a_browser(
        self, client, queued, monkeypatch
    ):
        def boom(*a, **k):
            raise AssertionError("the API process must not open a browser in production")

        monkeypatch.setattr(connect.MANAGER, "start", boom)
        r = await client.post(f"{API}/connect", json={"platform": "reed"})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["state"] == "opening"
        assert body["done"] is False
        assert "automation host" in body["detail"]

        # Polled from the database, so any serverless instance can answer.
        poll = await client.get(f"{API}/connect/{body['id']}")
        assert poll.status_code == 200
        assert poll.json()["state"] == "opening"

    async def test_a_second_click_reuses_the_pending_request(self, client, queued):
        a = (await client.post(f"{API}/connect", json={"platform": "reed"})).json()
        b = (await client.post(f"{API}/connect", json={"platform": "reed"})).json()
        assert a["id"] == b["id"]

    async def test_cancel_ends_the_request(self, client, queued):
        a = (await client.post(f"{API}/connect", json={"platform": "reed"})).json()
        r = await client.delete(f"{API}/connect/{a['id']}")
        assert r.status_code == 200
        assert r.json()["state"] == "cancelled"
        assert r.json()["done"] is True

    async def test_another_users_request_is_404(self, client, queued, db_session):
        row = PlatformSession(
            user_id="someoneelse00000000000000000000b",
            platform="reed",
            state=SessionState.INTERACTIVE_AVAILABLE,
        )
        db_session.add(row)
        await db_session.commit()
        assert (await client.get(f"{API}/connect/{row.id}")).status_code == 404

    async def test_a_stale_claim_is_requeued(self, client, queued, db_session, current_user):
        row = PlatformSession(
            user_id=current_user.id,
            platform="reed",
            state=SessionState.HUMAN_VERIFICATION_REQUIRED,
        )
        db_session.add(row)
        await db_session.commit()
        row.updated_at = datetime.now(UTC) - timedelta(hours=1)
        await db_session.commit()
        body = (await client.post(f"{API}/connect", json={"platform": "reed"})).json()
        assert body["state"] == "opening"


class TestSavingASession:
    async def test_import_marks_the_session_active(self, db_session, current_user):
        row = await service.import_session(db_session, current_user.id, "reed", STATE)
        assert row.state == SessionState.SESSION_ACTIVE

    async def test_settings_shows_the_platform_connected(self, db_session, current_user):
        await service.import_session(db_session, current_user.id, "reed", STATE)
        listing = await platform_service.list_platforms(db_session, current_user.id)
        reed = next(p for p in listing.platforms if p.key == "reed")
        assert reed.connected is True

    async def test_persist_stores_the_capture(self, bound_factory, current_user):
        attempt = ConnectAttempt(id="a1", user_id=current_user.id, platform="reed")
        await ConnectManager()._persist(attempt, STATE)
        assert attempt.state == ConnectState.CONNECTED


class TestHostRunsQueuedConnect:
    async def _request(self, factory, user_id: str) -> str:
        async with factory() as db:
            row = await service.request_connect(db, user_id, "reed")
            return row.id

    async def test_only_one_host_claims_a_request(self, bound_factory, current_user):
        row_id = await self._request(bound_factory, current_user.id)
        async with bound_factory() as db:
            assert await connect.claim_connect(db, row_id) is True
        async with bound_factory() as db:
            assert await connect.claim_connect(db, row_id) is False

    async def test_a_completed_sign_in_is_stored_and_reported(
        self, bound_factory, current_user, monkeypatch
    ):
        async def fake_run(self, attempt, target):
            attempt.state = ConnectState.AWAITING_LOGIN
            await asyncio.sleep(0.05)
            await self._persist(attempt, STATE)

        monkeypatch.setattr(ConnectManager, "_run", fake_run)
        monkeypatch.setattr(connect, "POLL_INTERVAL", 0.01)
        row_id = await self._request(bound_factory, current_user.id)
        async with bound_factory() as db:
            assert await connect.claim_connect(db, row_id)

        outcome = await connect.run_queued_connect(row_id, current_user.id, "reed")

        assert outcome == ConnectState.CONNECTED
        async with bound_factory() as db:
            row = await db.get(PlatformSession, row_id)
            assert row.state == SessionState.SESSION_ACTIVE
            assert row.state_detail is None

    async def test_a_failure_is_reported_with_its_reason(
        self, bound_factory, current_user, monkeypatch
    ):
        async def fake_run(self, attempt, target):
            attempt.state = ConnectState.FAILED
            attempt.detail = "Executable doesn't exist"

        monkeypatch.setattr(ConnectManager, "_run", fake_run)
        row_id = await self._request(bound_factory, current_user.id)
        async with bound_factory() as db:
            await connect.claim_connect(db, row_id)

        await connect.run_queued_connect(row_id, current_user.id, "reed")

        async with bound_factory() as db:
            row = await db.get(PlatformSession, row_id)
            assert row.state == SessionState.AUTH_REQUIRED
            assert "Executable" in row.state_detail

    async def test_a_failed_reconnect_keeps_the_working_session(
        self, bound_factory, current_user, monkeypatch
    ):
        async with bound_factory() as db:
            await service.import_session(db, current_user.id, "reed", STATE)

        async def fake_run(self, attempt, target):
            attempt.state = ConnectState.TIMED_OUT
            attempt.detail = "No completed sign-in was detected."

        monkeypatch.setattr(ConnectManager, "_run", fake_run)
        row_id = await self._request(bound_factory, current_user.id)
        async with bound_factory() as db:
            await connect.claim_connect(db, row_id)
        await connect.run_queued_connect(row_id, current_user.id, "reed")

        async with bound_factory() as db:
            row = await db.get(PlatformSession, row_id)
            assert row.state == SessionState.SESSION_ACTIVE

    async def test_cancel_from_the_web_app_closes_the_window(
        self, bound_factory, current_user, monkeypatch
    ):
        async def fake_run(self, attempt, target):
            attempt.state = ConnectState.AWAITING_LOGIN
            await asyncio.wait_for(attempt.cancelled.wait(), timeout=2)
            attempt.state = ConnectState.CANCELLED

        monkeypatch.setattr(ConnectManager, "_run", fake_run)
        monkeypatch.setattr(connect, "POLL_INTERVAL", 0.01)
        row_id = await self._request(bound_factory, current_user.id)
        async with bound_factory() as db:
            await connect.claim_connect(db, row_id)
            row = await db.get(PlatformSession, row_id)
            await service.settle_connect(
                db, row, state=SessionState.NOT_CONNECTED, detail="Cancelled."
            )

        outcome = await connect.run_queued_connect(row_id, current_user.id, "reed")
        assert outcome == ConnectState.CANCELLED


class TestApiKeySources:
    async def test_adzuna_offers_no_sign_in(self, db_session, current_user):
        listing = await platform_service.list_platforms(db_session, current_user.id)
        adzuna = next(p for p in listing.platforms if p.key == "adzuna")
        assert adzuna.needs_credential is False
        action = next(a for a in adzuna.actions if a.key == "connect")
        assert action.available is False
        assert "API key" in action.reason

    async def test_login_portals_still_offer_connect(self, db_session, current_user):
        listing = await platform_service.list_platforms(db_session, current_user.id)
        for key in ("reed", "linkedin"):
            p = next(p for p in listing.platforms if p.key == key)
            assert next(a for a in p.actions if a.key == "connect").available is True


class TestPlatformTest:
    async def test_an_adapter_without_a_live_check_reports_why(self, db_session):
        result = await platform_service.test_platforms(db_session, TEST_USER_ID, ["indeed"])
        indeed = result.results[0]
        assert indeed.ok is False
        assert "health_check" not in indeed.detail
        assert indeed.detail  # the registry's own reason, not an AttributeError
