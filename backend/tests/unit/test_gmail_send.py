"""Unit tests for services.gmail_send — application-confirmation emails.

Two concerns, both of which used to be silent: the email's *honesty* (it is worded for the
application's confirmation state, and a simulated run sends nothing) and its *observability*
(every attempt records its outcome on the application timeline). httpx is fully mocked; the
encrypted-token roundtrip goes through the real CredentialStore.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.secrets import CredentialStore
from app.core.secrets.local import LocalSecretsProvider
from app.models.application import Application
from app.models.application_event import ApplicationEvent
from app.models.enums import (
    ApplicationEventType,
    ApplicationStatus,
    ApplyMode,
    ConfirmationState,
)
from app.models.job import Job
from app.models.user import User
from app.services import gmail_auth, gmail_send
from app.services.gmail_send import NotifyOutcome
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


async def _user(db_session) -> None:
    db_session.add(User(id=TEST_USER_ID, email="candidate@example.com", hashed_password="x"))
    await db_session.commit()


class TestSendApplicationConfirmation:
    async def test_not_configured_sends_nothing(self, db_session, monkeypatch) -> None:
        monkeypatch.setattr(gmail_auth, "get_settings", lambda: _fake_settings(client_id=""))
        outcome = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
        )
        assert outcome is NotifyOutcome.NOT_CONFIGURED

    async def test_not_connected_sends_nothing(self, db_session) -> None:
        outcome = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
        )
        assert outcome is NotifyOutcome.NOT_CONNECTED

    async def test_a_simulated_run_sends_no_email(self, db_session, monkeypatch) -> None:
        # Even fully connected, a simulated submission must not claim an application went out.
        await _user(db_session)
        await _connect(db_session)
        called = {"n": 0}
        _mock_transport(monkeypatch, lambda r: called.__setitem__("n", called["n"] + 1) or httpx.Response(200, json={}))
        outcome = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
            confirmation_state=ConfirmationState.SIMULATED,
        )
        assert outcome is NotifyOutcome.SKIPPED_SIMULATED
        assert called["n"] == 0, "no Gmail request for a simulated run"

    async def test_confirmed_message_reads_as_applied(self, db_session, monkeypatch) -> None:
        await _user(db_session)
        await _connect(db_session)
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.read()
            return httpx.Response(200, json={"id": "msg-1"})

        _mock_transport(monkeypatch, handler)
        outcome = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="Senior PM", company="Acme", platform="linkedin",
            confirmation_state=ConfirmationState.CONFIRMED,
        )
        assert outcome is NotifyOutcome.SENT
        import json as _json

        decoded = base64.urlsafe_b64decode(
            _json.loads(captured["body"])["raw"].encode("ascii")
        ).decode()
        assert "candidate@example.com" in decoded
        assert "Applied: Senior PM at Acme" in decoded
        assert "acknowledged" in decoded

    async def test_unconfirmed_message_asks_the_operator_to_verify(
        self, db_session, monkeypatch
    ) -> None:
        await _user(db_session)
        await _connect(db_session)
        captured = {}
        _mock_transport(
            monkeypatch,
            lambda r: captured.__setitem__("body", r.read()) or httpx.Response(200, json={}),
        )
        outcome = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
            confirmation_state=ConfirmationState.UNCONFIRMED,
        )
        assert outcome is NotifyOutcome.SENT
        decoded = base64.urlsafe_b64decode(
            __import__("json").loads(captured["body"])["raw"].encode("ascii")
        ).decode()
        # The MIME body is quoted-printable (soft line breaks), so assert on the unwrapped
        # subject line plus the presence of the verify-yourself framing.
        assert "Submitted (please verify): PM at Acme" in decoded
        assert "verify" in decoded.lower()

    async def test_insufficient_scope_is_its_own_outcome(self, db_session, monkeypatch) -> None:
        await _user(db_session)
        await _connect(db_session)
        _mock_transport(monkeypatch, lambda r: httpx.Response(403, json={"error": "scope"}))
        outcome = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
        )
        assert outcome is NotifyOutcome.INSUFFICIENT_SCOPE

    async def test_transient_http_error_is_failed_not_raised(
        self, db_session, monkeypatch
    ) -> None:
        await _user(db_session)
        await _connect(db_session)
        _mock_transport(monkeypatch, lambda r: httpx.Response(500, json={"error": "boom"}))
        outcome = await gmail_send.send_application_confirmation(
            db_session, TEST_USER_ID, job_title="PM", company="Acme", platform="linkedin",
        )
        assert outcome is NotifyOutcome.FAILED


async def _seed_app(db, sample_job_data, confirmation_state) -> Application:
    job = Job(**sample_job_data)
    db.add(job)
    await db.flush()
    app = Application(
        user_id=TEST_USER_ID, job_id=job.id, status=ApplicationStatus.APPLIED,
        apply_mode=ApplyMode.AUTONOMOUS, confirmation_state=confirmation_state,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


async def _notes(db, app) -> list[ApplicationEvent]:
    rows = (await db.execute(
        select(ApplicationEvent).where(
            ApplicationEvent.application_id == app.id,
            ApplicationEvent.event_type == ApplicationEventType.NOTE_ADDED,
        )
    )).scalars().all()
    return list(rows)


class TestNotifyApplicationSubmitted:
    """The self-recording entry point: whatever happens, the timeline says what."""

    async def test_records_sent_on_the_timeline(
        self, db_session, sample_job_data, monkeypatch
    ) -> None:
        await _user(db_session)
        await _connect(db_session)
        _mock_transport(monkeypatch, lambda r: httpx.Response(200, json={"id": "m"}))
        app = await _seed_app(db_session, sample_job_data, ConfirmationState.CONFIRMED)

        outcome = await gmail_send.notify_application_submitted(
            db_session, app, job_title="PM", company="Acme", platform="linkedin",
        )
        assert outcome is NotifyOutcome.SENT
        notes = await _notes(db_session, app)
        assert len(notes) == 1 and notes[0].payload == {"notification": "sent"}

    async def test_records_why_no_email_when_gmail_not_connected(
        self, db_session, sample_job_data
    ) -> None:
        await _user(db_session)  # connected = False (no token stored)
        app = await _seed_app(db_session, sample_job_data, ConfirmationState.CONFIRMED)

        outcome = await gmail_send.notify_application_submitted(
            db_session, app, job_title="PM", company="Acme", platform="linkedin",
        )
        assert outcome is NotifyOutcome.NOT_CONNECTED
        notes = await _notes(db_session, app)
        assert len(notes) == 1
        assert notes[0].payload == {"notification": "not_connected"}
        assert "not connected" in notes[0].summary.lower()

    async def test_simulated_run_is_recorded_but_sends_nothing(
        self, db_session, sample_job_data, monkeypatch
    ) -> None:
        await _user(db_session)
        await _connect(db_session)
        called = {"n": 0}
        _mock_transport(monkeypatch, lambda r: called.__setitem__("n", called["n"] + 1) or httpx.Response(200, json={}))
        app = await _seed_app(db_session, sample_job_data, ConfirmationState.SIMULATED)

        outcome = await gmail_send.notify_application_submitted(
            db_session, app, job_title="PM", company="Acme", platform="linkedin",
        )
        assert outcome is NotifyOutcome.SKIPPED_SIMULATED
        assert called["n"] == 0
        notes = await _notes(db_session, app)
        assert len(notes) == 1 and notes[0].payload == {"notification": "skipped_simulated"}
