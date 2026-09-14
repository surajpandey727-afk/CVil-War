"""Unit tests for services.gmail_auth — the OAuth handshake and token refresh.

httpx is fully mocked; the token exchange/refresh endpoints never hit the real network. The
encrypted-token roundtrip goes through the real CredentialStore against the test DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core.secrets import CredentialStore
from app.core.secrets.local import LocalSecretsProvider
from app.core.security import decode_token
from app.models.user import User
from app.services import gmail_auth
from tests.conftest import TEST_USER_ID

_RealAsyncClient = httpx.AsyncClient


def _fake_settings(*, client_id: str = "cid", client_secret: str = "csecret") -> SimpleNamespace:
    return SimpleNamespace(
        gmail_client_id=SimpleNamespace(get_secret_value=lambda: client_id),
        gmail_client_secret=SimpleNamespace(get_secret_value=lambda: client_secret),
        gmail_redirect_uri="https://app.example.com/callback",
    )


def _mock_transport(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: _RealAsyncClient(transport=httpx.MockTransport(handler), **kw),
    )


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(gmail_auth, "get_settings", _fake_settings)
    # One provider instance for the whole test, matching the platform-session test pattern —
    # a fresh Fernet key per call would make each CredentialStore() unable to decrypt what a
    # previous one encrypted, since gmail_auth constructs a new CredentialStore() per call.
    provider = LocalSecretsProvider([Fernet.generate_key().decode()])
    monkeypatch.setattr(
        "app.core.secrets.credential_store.get_secrets_provider", lambda: provider
    )
    yield


class TestAuthorizeUrl:
    def test_raises_when_not_configured(self, monkeypatch) -> None:
        monkeypatch.setattr(gmail_auth, "get_settings", lambda: _fake_settings(client_id=""))
        with pytest.raises(gmail_auth.GmailNotConfiguredError):
            gmail_auth.authorize_url(TEST_USER_ID)

    def test_url_carries_a_state_that_decodes_to_the_user(self) -> None:
        url = gmail_auth.authorize_url(TEST_USER_ID)
        assert "client_id=cid" in url
        assert "scope=" in url

        from urllib.parse import parse_qs, urlparse

        state = parse_qs(urlparse(url).query)["state"][0]
        payload = decode_token(state, expected_type="oauth_state")
        assert payload["sub"] == TEST_USER_ID


class TestExchangeAndRefresh:
    async def test_exchange_code_stores_token(self, db_session, monkeypatch) -> None:
        db_session.add(User(id=TEST_USER_ID, email="u@x.com", hashed_password="x"))
        await db_session.commit()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
            })

        _mock_transport(monkeypatch, handler)

        await gmail_auth.exchange_code(db_session, TEST_USER_ID, "auth-code")

        token = await CredentialStore().get_oauth_token(db_session, TEST_USER_ID, "gmail")
        assert token["access_token"] == "at-1"
        assert token["refresh_token"] == "rt-1"
        assert await gmail_auth.is_connected(db_session, TEST_USER_ID) is True

    async def test_get_valid_access_token_raises_when_never_connected(self, db_session) -> None:
        with pytest.raises(gmail_auth.GmailNotConnectedError):
            await gmail_auth.get_valid_access_token(db_session, TEST_USER_ID)

    async def test_returns_stored_token_when_not_near_expiry(self, db_session) -> None:
        await CredentialStore().put_oauth_token(db_session, TEST_USER_ID, "gmail", {
            "access_token": "still-good",
            "refresh_token": "rt-1",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        })
        token = await gmail_auth.get_valid_access_token(db_session, TEST_USER_ID)
        assert token == "still-good"

    async def test_refreshes_when_near_expiry_and_keeps_old_refresh_token(
        self, db_session, monkeypatch
    ) -> None:
        await CredentialStore().put_oauth_token(db_session, TEST_USER_ID, "gmail", {
            "access_token": "stale",
            "refresh_token": "rt-original",
            "expires_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        })

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.read().decode()
            # Google's refresh grant does not return a new refresh_token.
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})

        _mock_transport(monkeypatch, handler)

        token = await gmail_auth.get_valid_access_token(db_session, TEST_USER_ID)

        assert token == "fresh"
        assert "refresh_token=rt-original" in captured["body"]
        stored = await CredentialStore().get_oauth_token(db_session, TEST_USER_ID, "gmail")
        assert stored["access_token"] == "fresh"
        assert stored["refresh_token"] == "rt-original"  # preserved, not dropped


class TestDisconnect:
    async def test_disconnect_removes_the_token(self, db_session) -> None:
        await CredentialStore().put_oauth_token(db_session, TEST_USER_ID, "gmail", {
            "access_token": "a", "refresh_token": "r",
            "expires_at": datetime.now(UTC).isoformat(),
        })
        assert await gmail_auth.disconnect(db_session, TEST_USER_ID) is True
        assert await gmail_auth.is_connected(db_session, TEST_USER_ID) is False

    async def test_disconnect_when_nothing_stored_returns_false(self, db_session) -> None:
        assert await gmail_auth.disconnect(db_session, TEST_USER_ID) is False
