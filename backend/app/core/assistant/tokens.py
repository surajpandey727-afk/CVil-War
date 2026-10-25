"""Signed, expiring confirmation tokens for the Assistant's consequential actions.

The Vercel API is serverless: the request that proposes an action and the request that
confirms it may land on different instances with no shared memory, and Redis is optional.
So the pending action is not stored anywhere — it is *encoded in the token itself* and signed
with an HMAC keyed from ``AUTH__SECRET_KEY``. The signature binds the action, its parameters,
the user it was proposed for and its expiry; changing any of them invalidates the token.

Replay inside the expiry window is blocked best-effort by remembering spent nonces (Redis when
available, else in-process). The actions themselves are also idempotent (creating an
application dedupes on the job; approval only touches staged rows), so a replay that slips
past an instance-local nonce set cannot do anything a first confirm did not.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.config.settings import get_settings

#: How long a proposed action stays confirmable.
TOKEN_TTL_SECONDS = 600
_DOMAIN = b"cvilwar.assistant.confirm.v1"


class TokenError(ValueError):
    """The token is malformed, forged, expired, already used or someone else's."""


@dataclass(frozen=True)
class PendingAction:
    """A decoded, verified action awaiting execution."""

    action: str
    params: dict[str, Any]
    user_id: str
    expires_at: int
    nonce: str


def _key() -> bytes:
    secret = get_settings().auth.secret_key.get_secret_value().encode()
    # Domain-separated so this key can never validate a JWT or anything else signed with
    # the same root secret.
    return hmac.new(secret, _DOMAIN, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(user_id: str, action: str, params: dict[str, Any], *, now: float | None = None) -> str:
    """Encode and sign one pending action for ``user_id``."""
    issued = int(now if now is not None else time.time())
    payload = {
        "u": user_id,
        "a": action,
        "p": params,
        "e": issued + TOKEN_TTL_SECONDS,
        "n": secrets.token_urlsafe(9),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token: str, user_id: str, *, now: float | None = None) -> PendingAction:
    """Check signature, owner and expiry; return the action. Raises :class:`TokenError`."""
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 4096:
        raise TokenError("Malformed confirmation token.")
    body, sig = token.split(".")
    expected = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise TokenError("This confirmation is not valid.")
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenError("Malformed confirmation token.") from exc
    if not hmac.compare_digest(str(payload.get("u", "")), user_id):
        raise TokenError("This confirmation belongs to a different account.")
    expires = int(payload.get("e", 0))
    if (now if now is not None else time.time()) > expires:
        raise TokenError("This confirmation has expired. Ask the assistant again.")
    return PendingAction(
        action=str(payload.get("a", "")),
        params=dict(payload.get("p") or {}),
        user_id=user_id,
        expires_at=expires,
        nonce=str(payload.get("n", "")),
    )


class _SpentNonces:
    """In-process fallback record of confirmed nonces (bounded, self-pruning)."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def claim(self, nonce: str, expires_at: int) -> bool:
        now = int(time.time())
        with self._lock:
            if len(self._seen) > 5000:
                self._seen = {n: e for n, e in self._seen.items() if e >= now}
            if nonce in self._seen:
                return False
            self._seen[nonce] = expires_at
            return True


_local = _SpentNonces()


async def claim_once(pending: PendingAction, redis: Any | None) -> bool:
    """Mark the token's nonce as spent. False when it was already confirmed."""
    if redis is not None:
        try:
            ttl = max(1, pending.expires_at - int(time.time()))
            ok = await redis.set(f"assistant:nonce:{pending.nonce}", "1", nx=True, ex=ttl)
            return bool(ok)
        except Exception:  # a dead Redis falls back to the per-process set, never fails open
            pass
    return _local.claim(pending.nonce, pending.expires_at)
