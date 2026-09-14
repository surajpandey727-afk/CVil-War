"""Unit tests for services.inbox_sync — Gmail message matching and classification.

httpx is fully mocked; gmail_auth's own token handling is mocked out too (it has its own
dedicated test file) so these tests exercise only the sync/match/classify logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import select

from app.db.tenant import current_user_id
from app.models.application import Application
from app.models.communication_event import CommunicationEvent
from app.models.job import Job
from app.models.user import User
from app.services import inbox_sync
from tests.conftest import TEST_USER_ID

_RealAsyncClient = httpx.AsyncClient


def _uid(prefix: str) -> str:
    return prefix.ljust(30, "0") + "aa"


class _CtxManager:
    """Async-context-manager stand-in for async_session_factory() in tests — see the
    identical helper in test_discovery_scheduler.py for why this is needed."""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


def _mock_transport(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: _RealAsyncClient(transport=httpx.MockTransport(handler), **kw),
    )


def _gmail_handler(messages: dict[str, dict]):
    """A fake Gmail API: ``messages`` maps message id -> {sender, subject, snippet}."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200, json={"messages": [{"id": mid} for mid in messages]},
            )
        message_id = request.url.path.rsplit("/", 1)[-1]
        msg = messages[message_id]
        return httpx.Response(200, json={
            "id": message_id,
            "snippet": msg["snippet"],
            "internalDate": str(int(datetime(2026, 8, 1, tzinfo=UTC).timestamp() * 1000)),
            "payload": {"headers": [
                {"name": "Subject", "value": msg["subject"]},
                {"name": "From", "value": msg["sender"]},
            ]},
        })

    return handler


class TestSenderCompanyHint:
    def test_uses_display_name_when_present(self) -> None:
        assert inbox_sync._sender_company_hint('"Monzo Recruiting" <hr@monzo.com>') == "Monzo Recruiting"

    def test_falls_back_to_email_domain_label(self) -> None:
        assert inbox_sync._sender_company_hint("noreply@monzo.com") == "monzo"

    def test_empty_sender_returns_empty(self) -> None:
        assert inbox_sync._sender_company_hint("") == ""


class TestMatchApplication:
    def test_matches_the_one_candidate_at_that_employer(self) -> None:
        app = Application(user_id=TEST_USER_ID, job_id="j1", status="applied")
        candidates = [(app, "Monzo Bank Ltd")]
        assert inbox_sync._match_application('"Monzo" <hr@monzo.com>', candidates) is app

    def test_ambiguous_when_two_applications_at_same_employer(self) -> None:
        app1 = Application(user_id=TEST_USER_ID, job_id="j1", status="applied")
        app2 = Application(user_id=TEST_USER_ID, job_id="j2", status="applied")
        candidates = [(app1, "Monzo"), (app2, "Monzo")]
        assert inbox_sync._match_application('"Monzo" <hr@monzo.com>', candidates) is None

    def test_no_match_when_no_sender_hint(self) -> None:
        app = Application(user_id=TEST_USER_ID, job_id="j1", status="applied")
        assert inbox_sync._match_application("", [(app, "Monzo")]) is None


async def _seed_applied(db, *, company: str, platform_job_id: str) -> Application:
    job = Job(
        user_id=TEST_USER_ID, platform="linkedin", platform_job_id=platform_job_id,
        title="Data Scientist", company=company, url="https://x",
    )
    db.add(job)
    await db.flush()
    app = Application(
        user_id=TEST_USER_ID, job_id=job.id, status="applied",
        applied_at=datetime.now(UTC),
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


class TestSyncInbox:
    async def test_matched_reply_writes_timeline_and_communication_event(
        self, db_session, monkeypatch
    ) -> None:
        db_session.add(User(id=TEST_USER_ID, email="u@x.com", hashed_password="x"))
        await db_session.commit()
        app = await _seed_applied(db_session, company="Monzo", platform_job_id="p1")

        monkeypatch.setattr(
            inbox_sync.gmail_auth, "get_valid_access_token", AsyncMock(return_value="tok"),
        )
        _mock_transport(monkeypatch, _gmail_handler({
            "m1": {
                "sender": '"Monzo Recruiting" <hr@monzo.com>',
                "subject": "Your application",
                "snippet": "Unfortunately, we have decided not to move forward.",
            },
        }))

        result = await inbox_sync.sync_inbox(db_session, TEST_USER_ID)

        assert result.fetched == 1
        assert result.matched_to_application == 1
        assert result.unmatched == 0

        events = (
            await db_session.execute(
                select(CommunicationEvent).where(CommunicationEvent.external_id == "m1")
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].application_id == app.id
        assert events[0].classified_as == "rejection"

        await db_session.refresh(app)
        timeline = await db_session.execute(select(Application).where(Application.id == app.id))
        assert timeline.scalar_one().status is not None  # sanity: row still intact

    async def test_unmatched_reply_lands_without_an_application(
        self, db_session, monkeypatch
    ) -> None:
        db_session.add(User(id=TEST_USER_ID, email="u@x.com", hashed_password="x"))
        await db_session.commit()
        await _seed_applied(db_session, company="Monzo", platform_job_id="p1")

        monkeypatch.setattr(
            inbox_sync.gmail_auth, "get_valid_access_token", AsyncMock(return_value="tok"),
        )
        _mock_transport(monkeypatch, _gmail_handler({
            "m1": {
                "sender": "newsletter@unrelated.com", "subject": "Hi",
                "snippet": "Just checking in.",
            },
        }))

        result = await inbox_sync.sync_inbox(db_session, TEST_USER_ID)

        assert result.matched_to_application == 0
        assert result.unmatched == 1
        event = (
            await db_session.execute(select(CommunicationEvent))
        ).scalar_one()
        assert event.application_id is None
        assert event.matched_confidence == 0.0

    async def test_second_sync_skips_already_seen_messages(self, db_session, monkeypatch) -> None:
        db_session.add(User(id=TEST_USER_ID, email="u@x.com", hashed_password="x"))
        await db_session.commit()
        await _seed_applied(db_session, company="Monzo", platform_job_id="p1")

        monkeypatch.setattr(
            inbox_sync.gmail_auth, "get_valid_access_token", AsyncMock(return_value="tok"),
        )
        _mock_transport(monkeypatch, _gmail_handler({
            "m1": {"sender": "x@unrelated.com", "subject": "Hi", "snippet": "hi"},
        }))

        first = await inbox_sync.sync_inbox(db_session, TEST_USER_ID)
        second = await inbox_sync.sync_inbox(db_session, TEST_USER_ID)

        assert first.unmatched == 1
        assert second.already_seen == 1
        assert second.unmatched == 0
        total = (await db_session.execute(select(CommunicationEvent))).scalars().all()
        assert len(total) == 1  # not duplicated


class TestRunInboxSyncForAllUsers:
    """The Tracking agent's real trigger point — mirrors discovery_scheduler's own
    fan-out tests exactly (same tenant-scoping and per-user isolation guarantees)."""

    async def test_only_connected_users_are_synced(self, db_session) -> None:
        connected = User(id=_uid("connected"), email="a@x.com", is_active=True)
        not_connected = User(id=_uid("notconn"), email="b@x.com", is_active=True)
        db_session.add_all([connected, not_connected])
        await db_session.commit()

        seen: list[str] = []

        async def _fake_is_connected(db, user_id):
            return user_id == connected.id

        async def _fake_sync(db, user_id):
            seen.append(user_id)
            return inbox_sync.InboxSyncResult(0, 0, 0, 0, [])

        with patch.object(
            inbox_sync, "async_session_factory", return_value=_CtxManager(db_session)
        ), patch.object(
            inbox_sync.gmail_auth, "is_connected", new=_fake_is_connected
        ), patch.object(inbox_sync, "sync_inbox", new=_fake_sync):
            await inbox_sync.run_inbox_sync_for_all_users({})

        assert seen == [connected.id]

    async def test_resets_tenant_context_per_user(self, db_session) -> None:
        user = User(id=_uid("scoped"), email="scoped@x.com", is_active=True)
        db_session.add(user)
        await db_session.commit()

        seen_during_call: list[str | None] = []

        async def _fake_sync(db, user_id):
            seen_during_call.append(current_user_id.get())
            return inbox_sync.InboxSyncResult(0, 0, 0, 0, [])

        outer_token = current_user_id.set("outer-context")
        try:
            with patch.object(
                inbox_sync, "async_session_factory", return_value=_CtxManager(db_session)
            ), patch.object(
                inbox_sync.gmail_auth, "is_connected", new=AsyncMock(return_value=True)
            ), patch.object(inbox_sync, "sync_inbox", new=_fake_sync):
                await inbox_sync.run_inbox_sync_for_all_users({})
            assert seen_during_call == [user.id]
            assert current_user_id.get() == "outer-context"
        finally:
            current_user_id.reset(outer_token)

    async def test_one_user_failing_does_not_stop_the_cycle(self, db_session) -> None:
        u1 = User(id=_uid("failing"), email="f@x.com", is_active=True)
        u2 = User(id=_uid("succeed"), email="s@x.com", is_active=True)
        db_session.add_all([u1, u2])
        await db_session.commit()

        seen: list[str] = []

        async def _fake_sync(db, user_id):
            if user_id == u1.id:
                raise RuntimeError("boom")
            seen.append(user_id)
            return inbox_sync.InboxSyncResult(0, 0, 0, 0, [])

        with patch.object(
            inbox_sync, "async_session_factory", return_value=_CtxManager(db_session)
        ), patch.object(
            inbox_sync.gmail_auth, "is_connected", new=AsyncMock(return_value=True)
        ), patch.object(inbox_sync, "sync_inbox", new=_fake_sync):
            await inbox_sync.run_inbox_sync_for_all_users({})  # must not raise

        assert seen == [u2.id]

    async def test_records_a_tracking_agent_run(self, db_session) -> None:
        from sqlalchemy import select as sa_select

        from app.models.agent_run import AgentRun
        from app.models.enums import AgentName, AgentRunStatus

        # TEST_USER_ID, not a fresh id: the autouse _tenant_context fixture scopes every
        # plain select() in this test to TEST_USER_ID, so the verification query below would
        # find nothing for any other user id even though the row was written correctly.
        user = User(id=TEST_USER_ID, email="t@x.com", is_active=True)
        db_session.add(user)
        await db_session.commit()

        async def _fake_sync(db, user_id):
            return inbox_sync.InboxSyncResult(3, 0, 2, 1, [])

        with patch.object(
            inbox_sync, "async_session_factory", return_value=_CtxManager(db_session)
        ), patch.object(
            inbox_sync.gmail_auth, "is_connected", new=AsyncMock(return_value=True)
        ), patch.object(inbox_sync, "sync_inbox", new=_fake_sync):
            await inbox_sync.run_inbox_sync_for_all_users({})

        run = (
            await db_session.execute(sa_select(AgentRun).where(AgentRun.user_id == user.id))
        ).scalar_one()
        assert run.agent_name == AgentName.TRACKING
        assert run.status == AgentRunStatus.DONE
        assert "2 matched" in run.output_summary
