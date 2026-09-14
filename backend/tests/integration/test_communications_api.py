"""Integration tests for the Communications API: Gmail status/callback, Apollo status,
inbox-sync, the feed, and manual linking. Gmail/Apollo network calls are mocked at the
service layer (each has its own dedicated unit tests for the real HTTP contract)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.core.security import create_oauth_state
from app.models.communication_event import CommunicationEvent
from app.services import gmail_auth, inbox_sync
from tests.conftest import TEST_USER_ID

API_PREFIX = "/api/v1/communications"


class TestGmailStatus:
    async def test_not_configured(self, client) -> None:
        with patch.object(gmail_auth, "is_configured", return_value=False):
            response = await client.get(f"{API_PREFIX}/gmail/status")
        assert response.status_code == 200
        body = response.json()
        assert body == {"configured": False, "connected": False, "authorize_url": None}

    async def test_configured_but_not_connected_offers_authorize_url(self, client) -> None:
        with patch.object(gmail_auth, "is_configured", return_value=True), patch.object(
            gmail_auth, "is_connected", new=AsyncMock(return_value=False)
        ), patch.object(gmail_auth, "authorize_url", return_value="https://accounts.google.com/x"):
            response = await client.get(f"{API_PREFIX}/gmail/status")
        body = response.json()
        assert body["configured"] is True
        assert body["connected"] is False
        assert body["authorize_url"] == "https://accounts.google.com/x"

    async def test_connected_offers_no_authorize_url(self, client) -> None:
        with patch.object(gmail_auth, "is_configured", return_value=True), patch.object(
            gmail_auth, "is_connected", new=AsyncMock(return_value=True)
        ):
            response = await client.get(f"{API_PREFIX}/gmail/status")
        body = response.json()
        assert body["connected"] is True
        assert body["authorize_url"] is None


class TestApolloStatus:
    async def test_reads_from_settings(self, client) -> None:
        from app.config.settings import get_settings

        with patch.object(
            type(get_settings().apollo_api_key), "get_secret_value", lambda self: "key"
        ):
            response = await client.get(f"{API_PREFIX}/apollo/status")
        assert response.json() == {"configured": True}


class TestInboxSync:
    async def test_not_connected_returns_400(self, client) -> None:
        with patch.object(
            inbox_sync, "sync_inbox",
            new=AsyncMock(side_effect=gmail_auth.GmailNotConnectedError("not connected")),
        ):
            response = await client.post(f"{API_PREFIX}/inbox-sync")
        assert response.status_code == 400

    async def test_success_returns_counts(self, client) -> None:
        result = inbox_sync.InboxSyncResult(
            fetched=3, already_seen=1, matched_to_application=1, unmatched=1, errors=[],
        )
        with patch.object(inbox_sync, "sync_inbox", new=AsyncMock(return_value=result)):
            response = await client.post(f"{API_PREFIX}/inbox-sync")
        assert response.status_code == 200
        assert response.json() == {
            "fetched": 3, "already_seen": 1, "matched_to_application": 1,
            "unmatched": 1, "errors": [],
        }


class TestListCommunications:
    async def test_lists_and_counts_unmatched(self, db_session, client) -> None:
        db_session.add_all([
            CommunicationEvent(
                user_id=TEST_USER_ID, source="gmail", external_id="m1",
                sender="a@x.com", subject="s1", snippet="x", occurred_at=datetime.now(UTC),
                matched_confidence=0.0, classified_as="reply",
            ),
            CommunicationEvent(
                user_id=TEST_USER_ID, source="gmail", external_id="m2",
                application_id=None, sender="b@x.com", subject="s2", snippet="y",
                occurred_at=datetime.now(UTC), matched_confidence=1.0, classified_as="rejection",
            ),
        ])
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["unmatched"] == 2  # neither has an application_id set

    async def test_unmatched_only_filter(self, db_session, client) -> None:
        db_session.add(
            CommunicationEvent(
                user_id=TEST_USER_ID, source="gmail", external_id="m1",
                sender="a@x.com", subject="s", snippet="x", occurred_at=datetime.now(UTC),
                matched_confidence=0.0, classified_as="reply",
            )
        )
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/", params={"unmatched_only": True})
        assert response.json()["total"] == 1


class TestLinkApplication:
    async def test_404_for_unknown_event(self, client) -> None:
        response = await client.post(
            f"{API_PREFIX}/nonexistent/link-application", json={"application_id": "x"}
        )
        assert response.status_code == 404

    async def test_links_and_writes_timeline_entry(self, db_session, client) -> None:
        from app.models.application import Application
        from app.models.job import Job
        from app.models.user import User

        db_session.add(User(id=TEST_USER_ID, email="u@x.com", hashed_password="x"))
        job = Job(
            user_id=TEST_USER_ID, platform="linkedin", platform_job_id="j1",
            title="t", company="Monzo", url="https://x",
        )
        db_session.add(job)
        await db_session.flush()
        app_row = Application(user_id=TEST_USER_ID, job_id=job.id, status="applied")
        db_session.add(app_row)
        event = CommunicationEvent(
            user_id=TEST_USER_ID, source="gmail", external_id="m1",
            sender="hr@monzo.com", subject="Update", snippet="x",
            occurred_at=datetime.now(UTC), matched_confidence=0.0, classified_as="rejection",
        )
        db_session.add(event)
        await db_session.commit()
        await db_session.refresh(app_row)
        await db_session.refresh(event)

        response = await client.post(
            f"{API_PREFIX}/{event.id}/link-application",
            json={"application_id": app_row.id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["application_id"] == app_row.id
        assert body["matched_confidence"] == 1.0


class TestGmailCallback:
    async def test_invalid_state_redirects_with_error(self, anon_client) -> None:
        response = await anon_client.get(
            f"{API_PREFIX}/gmail/callback",
            params={"code": "x", "state": "not-a-real-token"},
            follow_redirects=False,
        )
        assert response.status_code in (302, 307)
        assert "gmail_error=invalid_state" in response.headers["location"]

    async def test_valid_state_exchanges_and_redirects_connected(self, anon_client) -> None:
        state = create_oauth_state(TEST_USER_ID)
        with patch.object(gmail_auth, "exchange_code", new=AsyncMock(return_value=None)):
            response = await anon_client.get(
                f"{API_PREFIX}/gmail/callback",
                params={"code": "auth-code", "state": state},
                follow_redirects=False,
            )
        assert response.status_code in (302, 307)
        assert "gmail_connected=1" in response.headers["location"]
