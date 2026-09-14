"""Gmail OAuth: the one-time consent flow, and keeping the resulting token usable.

The operator authorises this app to read their Gmail exactly once, in their own browser, on
Google's own consent screen — the same "human does the actual sign-in" principle
``core.automation.connect`` uses for platform sessions, just via OAuth's standard redirect
dance instead of a captured browser session. Nothing here ever sees a Google password.

Read-only scope only (``gmail.readonly``): this integration detects replies, it never sends,
labels, or deletes anything in the operator's mailbox.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.secrets.credential_store import CredentialStore
from app.core.security import create_oauth_state

logger = structlog.get_logger(__name__)

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_TIMEOUT = 15.0
#: Refresh this long before the token's own expiry — never let a sync fail mid-run on an
#: access token that expires between the readiness check and the actual API call.
_REFRESH_MARGIN = timedelta(minutes=2)

PROVIDER = "gmail"


class GmailNotConfiguredError(Exception):
    """No Google Cloud OAuth client is set — see GMAIL_CLIENT_ID/SECRET in ``.env``."""


class GmailNotConnectedError(Exception):
    """The client is configured, but this operator has not completed the consent flow yet."""


def _require_client() -> tuple[str, str, str]:
    settings = get_settings()
    client_id = settings.gmail_client_id.get_secret_value()
    client_secret = settings.gmail_client_secret.get_secret_value()
    if not client_id or not client_secret:
        raise GmailNotConfiguredError(
            "No Gmail OAuth client is configured. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET "
            "in .env (from a Google Cloud OAuth client with the Gmail API enabled), then restart."
        )
    return client_id, client_secret, settings.gmail_redirect_uri


def authorize_url(user_id: str) -> str:
    """Where to send the operator's browser to grant read-only Gmail access.

    Carries a signed, short-lived ``state`` identifying the operator — the callback is a raw
    redirect from Google with no auth header this app's normal dependency can read, so this
    is how it recovers which account is completing the flow.
    """
    client_id, _secret, redirect_uri = _require_client()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",  # requests a refresh_token, not just a short-lived access one
        # Forces a refresh_token even on a re-consent — Google omits it otherwise.
        "prompt": "consent",
        "state": create_oauth_state(user_id),
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


async def exchange_code(
    db: AsyncSession, user_id: str, code: str
) -> None:
    """Trade the callback's one-time code for a token pair, and store it encrypted."""
    client_id, client_secret, redirect_uri = _require_client()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        body = response.json()

    await _store_token(db, user_id, body)
    logger.info("gmail.connected", user_id=user_id)


async def _store_token(db: AsyncSession, user_id: str, body: dict[str, Any]) -> None:
    expires_in = int(body.get("expires_in", 3600))
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
    existing = await CredentialStore().get_oauth_token(db, user_id, PROVIDER)
    await CredentialStore().put_oauth_token(db, user_id, PROVIDER, {
        "access_token": body["access_token"],
        # A refresh grant does not return a new refresh_token — keep the one already on file.
        "refresh_token": body.get("refresh_token") or (existing or {}).get("refresh_token"),
        "expires_at": expires_at,
    })


async def _refresh(db: AsyncSession, user_id: str, refresh_token: str) -> str:
    client_id, client_secret, _redirect = _require_client()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        body = response.json()

    body.setdefault("refresh_token", refresh_token)
    await _store_token(db, user_id, body)
    return str(body["access_token"])


async def get_valid_access_token(db: AsyncSession, user_id: str) -> str:
    """A usable access token, refreshing first if the stored one is expired or near-expiry.

    Raises ``GmailNotConnectedError`` if the operator has never completed the consent flow —
    a sync must offer "connect Gmail", not fail with an opaque 401 from Google.
    """
    token = await CredentialStore().get_oauth_token(db, user_id, PROVIDER)
    if token is None or not token.get("refresh_token"):
        raise GmailNotConnectedError("Gmail is not connected yet.")

    expires_at = datetime.fromisoformat(token["expires_at"])
    if datetime.now(UTC) >= expires_at - _REFRESH_MARGIN:
        return await _refresh(db, user_id, token["refresh_token"])
    return str(token["access_token"])


async def disconnect(db: AsyncSession, user_id: str) -> bool:
    """Forget the stored token. Does not revoke it on Google's side — the operator can do
    that from their own Google Account permissions page if they want to fully undo consent."""
    return await CredentialStore().delete_oauth_token(db, user_id, PROVIDER)


def is_configured() -> bool:
    """Whether the operator has set up a Google Cloud OAuth client at all."""
    settings = get_settings()
    return bool(
        settings.gmail_client_id.get_secret_value()
        and settings.gmail_client_secret.get_secret_value()
    )


async def is_connected(db: AsyncSession, user_id: str) -> bool:
    """Whether this operator has completed the consent flow (a refresh token is on file)."""
    token = await CredentialStore().get_oauth_token(db, user_id, PROVIDER)
    return bool(token and token.get("refresh_token"))
