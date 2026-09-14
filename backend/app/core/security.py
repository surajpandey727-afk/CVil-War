"""Password hashing and JWT helpers — hand-rolled PyJWT + pwdlib (Argon2id).

Chosen over fastapi-users (maintenance mode) because we hand-build multi-tenancy and
BYO-key anyway. The signing algorithm is hardcoded in ``decode_token`` (never read from
the token header) per RFC 8725.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.config.settings import get_settings
from app.core.exceptions import AuthError

_password_hash = PasswordHash.recommended()
# Hash of a random value, used for timing-safe verification when a user is not found.
DUMMY_HASH = _password_hash.hash(secrets.token_urlsafe(32))


def hash_password(plain: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Verify a password, running against ``DUMMY_HASH`` when no hash exists."""
    target = hashed or DUMMY_HASH
    try:
        return _password_hash.verify(plain, target)
    except Exception:
        return False


def _secret() -> str:
    return get_settings().auth.secret_key.get_secret_value()


def create_access_token(sub: str, *, expires_minutes: int | None = None) -> str:
    """Mint a short-lived access token for ``sub`` (the user id)."""
    auth = get_settings().auth
    minutes = expires_minutes if expires_minutes is not None else auth.access_token_expire_minutes
    now = datetime.now(UTC)
    payload = {"sub": sub, "type": "access", "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, _secret(), algorithm=auth.algorithm)


def create_ws_ticket(sub: str) -> str:
    """Mint a very short-lived ticket for authenticating a WebSocket handshake."""
    auth = get_settings().auth
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "type": "ws_ticket",
        "iat": now,
        "exp": now + timedelta(seconds=auth.ws_ticket_expire_seconds),
    }
    return jwt.encode(payload, _secret(), algorithm=auth.algorithm)


def create_oauth_state(sub: str) -> str:
    """Mint a short-lived, signed ``state`` value for a third-party OAuth redirect.

    The callback (a raw browser redirect from Google, carrying no auth header this app's
    normal dependency can read) uses this to recover which operator is completing the flow —
    the same problem ``create_ws_ticket`` solves for the WebSocket handshake, just with a
    longer window since a human clicking through Google's consent screen takes longer than a
    socket connecting.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "type": "oauth_state",
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    return jwt.encode(payload, _secret(), algorithm=get_settings().auth.algorithm)


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    """Decode and validate a JWT. Raises :class:`AuthError` on any failure."""
    auth = get_settings().auth
    try:
        payload: dict[str, Any] = jwt.decode(token, _secret(), algorithms=[auth.algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired token") from exc
    if expected_type is not None and payload.get("type") != expected_type:
        raise AuthError("Invalid token type")
    return payload


def generate_refresh_token() -> str:
    """Generate an opaque refresh token (stored only as a hash)."""
    return secrets.token_urlsafe(48)


def generate_reset_token() -> str:
    """Generate an opaque, single-use password-reset token (stored only as a hash)."""
    return secrets.token_urlsafe(48)


def hash_token(raw: str) -> str:
    """SHA-256 hash a refresh token for at-rest storage."""
    return hashlib.sha256(raw.encode()).hexdigest()
