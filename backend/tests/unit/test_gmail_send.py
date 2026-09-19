"""Unit tests for services.gmail_send — application-confirmation emails.

Mirrors test_gmail_auth.py's mocking pattern: httpx is fully mocked, never hits the real
network; the encrypted-token roundtrip goes through the real CredentialStore.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core.secrets import CredentialStore
from app.core.secrets.local import LocalSecretsProvider
from app.models.user import User
from app.services import gmail_auth, gmail_send
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
    provider = LocalSecretsProvider([Fernet.generate_key().decode()])
    monkeypatch.setattr(
        "app.core.secrets.credential_store.get_secrets_provider", lambda: provider
    )
    yield


async def _connect(db_session) -> None:
    await CredentialStore().put_oauth_token(db_session, TEST_USER_ID, "gmail", {
        "access_token": "at-1", "refresh_token": "rt-1",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    })


class TestSendApplicationConfirmation:
    async def test_not_configured_sends_nothing(self, db_session, monkeypatch) -> None:
        monkeypatch.setattr(gmail_auth, "get_settings", lambda: _fake_settings(client_id=""))
        sent = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
        )
        assert sent is False

    async def test_not_connected_sends_nothing(self, db_session) -> None:
        sent = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
        )
        assert sent is False

    async def test_sends_a_real_message_when_connected(self, db_session, monkeypatch) -> None:
        db_session.add(User(id=TEST_USER_ID, email="candidate@example.com", hashed_password="x"))
        await db_session.commit()
        await _connect(db_session)

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = request.read()
            return httpx.Response(200, json={"id": "msg-1"})

        _mock_transport(monkeypatch, handler)

        sent = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="Senior PM", company="Acme", platform="linkedin",
        )

        assert sent is True
        assert captured["url"].endswith("/messages/send")
        assert captured["auth"] == "Bearer at-1"
        import json as _json

        raw = _json.loads(captured["body"])["raw"]
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode()
        assert "candidate@example.com" in decoded
        assert "Senior PM" in decoded
        assert "Acme" in decoded

    async def test_insufficient_scope_is_treated_as_not_sent_not_an_error(
        self, db_session, monkeypatch
    ) -> None:
        db_session.add(User(id=TEST_USER_ID, email="candidate@example.com", hashed_password="x"))
        await db_session.commit()
        await _connect(db_session)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "insufficient scope"})

        _mock_transport(monkeypatch, handler)

        sent = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
        )
        assert sent is False

    async def test_transient_http_error_is_swallowed(self, db_session, monkeypatch) -> None:
        db_session.add(User(id=TEST_USER_ID, email="candidate@example.com", hashed_password="x"))
        await db_session.commit()
        await _connect(db_session)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        _mock_transport(monkeypatch, handler)

        sent = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
        )
        assert sent is False
