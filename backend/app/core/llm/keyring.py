"""Rotating API-key pool for a single LLM provider.

The provider fallback chain in :mod:`app.core.llm.client` rotates *models* — it cannot help
when one provider has several keys and the current one runs out of credit. That is the case
for pooled free-tier keys: the model is fine, the key is simply spent, and the correct move
is to retry the same model on the next key rather than degrade to a weaker provider.

Two failure modes are distinguished, because they warrant very different cooldowns:

* **Exhausted** — the key has no credit left (DeepSeek answers HTTP 402 "Insufficient
  Balance"; OpenAI-compatible providers say "exceeded your current quota"). Credit does not
  come back on its own, so the key is parked for a long cooldown instead of being retried
  every call and burning a round-trip each time.
* **Rate limited** — HTTP 429. Transient; a short cooldown is enough.

Cooldowns are held in memory, so a process restart re-tries every key once. That is
deliberate: it is the cheapest way to notice that a key has been topped up, and the cost of
being wrong is a single failed request.

This class is deliberately free of provider SDK imports so it can be unit-tested without a
network or litellm.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# Credit does not replenish, so park a spent key for a long time rather than retrying it on
# every call. Short enough that a manually topped-up key recovers the same day.
EXHAUSTED_COOLDOWN_S = 6 * 60 * 60
# 429s clear quickly; a short pause is enough to let the next key take the load.
RATE_LIMIT_COOLDOWN_S = 60.0


def mask_key(key: str) -> str:
    """Render a key safe for logs and the usage UI: ``sk-83d7…d677``.

    Never log or return a raw key — masked forms are what the admin/usage views display so an
    operator can tell *which* key is spent without the value being readable over a shoulder,
    in a screenshot, or in a log aggregator.
    """
    if len(key) <= 12:
        return "…"  # too short to mask meaningfully; reveal nothing
    return f"{key[:7]}…{key[-4:]}"


@dataclass
class _KeyState:
    key: str
    available_at: float = 0.0  # monotonic deadline; 0 = usable now
    reason: str = ""           # why it was parked, for the status view
    exhausted_count: int = 0
    rate_limited_count: int = 0
    success_count: int = 0


@dataclass
class KeyRing:
    """An ordered pool of interchangeable API keys for one provider.

    Keys are tried in the order supplied. ``next_key`` returns the first key not currently in
    cooldown, so a healthy pool always reuses the same key (keeping provider-side caching and
    rate-limit buckets warm) and only advances when one actually fails.
    """

    provider: str
    _states: list[_KeyState] = field(default_factory=list)

    @classmethod
    def from_csv(cls, provider: str, raw: str) -> KeyRing:
        """Build from a comma-separated env value, ignoring blanks and duplicates."""
        seen: set[str] = set()
        states: list[_KeyState] = []
        for part in raw.split(","):
            key = part.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            states.append(_KeyState(key=key))
        return cls(provider=provider, _states=states)

    def __len__(self) -> int:
        return len(self._states)

    @property
    def configured(self) -> bool:
        """True if this ring holds at least one key."""
        return bool(self._states)

    def next_key(self, *, _now: float | None = None) -> str | None:
        """Return the first key not in cooldown, or None if every key is parked."""
        now = time.monotonic() if _now is None else _now
        for state in self._states:
            if state.available_at <= now:
                return state.key
        return None

    def all_keys(self) -> list[str]:
        """Every key in pool order, regardless of cooldown (for building attempt lists)."""
        return [s.key for s in self._states]

    def usable_keys(self, *, _now: float | None = None) -> list[str]:
        """Keys not currently in cooldown, in pool order."""
        now = time.monotonic() if _now is None else _now
        return [s.key for s in self._states if s.available_at <= now]

    def _find(self, key: str) -> _KeyState | None:
        return next((s for s in self._states if s.key == key), None)

    def mark_exhausted(self, key: str, *, _now: float | None = None) -> None:
        """Park a key that has run out of credit."""
        state = self._find(key)
        if state is None:
            return
        now = time.monotonic() if _now is None else _now
        state.available_at = now + EXHAUSTED_COOLDOWN_S
        state.reason = "exhausted"
        state.exhausted_count += 1
        logger.warning(
            "llm_key.exhausted",
            provider=self.provider,
            key=mask_key(key),
            cooldown_s=EXHAUSTED_COOLDOWN_S,
            remaining_usable=len(self.usable_keys(_now=now)),
        )

    def mark_rate_limited(self, key: str, *, _now: float | None = None) -> None:
        """Park a key that is being throttled."""
        state = self._find(key)
        if state is None:
            return
        now = time.monotonic() if _now is None else _now
        state.available_at = now + RATE_LIMIT_COOLDOWN_S
        state.reason = "rate_limited"
        state.rate_limited_count += 1
        logger.info(
            "llm_key.rate_limited", provider=self.provider, key=mask_key(key)
        )

    def mark_success(self, key: str) -> None:
        """Clear any cooldown on a key that just worked."""
        state = self._find(key)
        if state is None:
            return
        state.available_at = 0.0
        state.reason = ""
        state.success_count += 1

    def status(self, *, _now: float | None = None) -> list[dict[str, object]]:
        """Masked, JSON-safe snapshot for the usage / system-health views."""
        now = time.monotonic() if _now is None else _now
        out: list[dict[str, object]] = []
        for index, state in enumerate(self._states):
            cooling = state.available_at > now
            out.append(
                {
                    "index": index,
                    "key": mask_key(state.key),
                    "status": state.reason if cooling else "available",
                    "cooldown_remaining_s": (
                        round(state.available_at - now) if cooling else 0
                    ),
                    "successes": state.success_count,
                    "times_exhausted": state.exhausted_count,
                    "times_rate_limited": state.rate_limited_count,
                }
            )
        return out


# Substrings that mean "this key has no credit left" rather than "this request was bad".
# DeepSeek returns HTTP 402 Insufficient Balance; OpenAI-compatible providers phrase the same
# condition as a quota message. Matched case-insensitively against the exception text.
_EXHAUSTED_HINTS = (
    "insufficient balance",
    "insufficient_quota",
    "exceeded your current quota",
    "quota exceeded",
    "billing",
    "payment required",
    "credit balance is too low",
)


_RINGS: dict[str, KeyRing] = {}


def get_keyring(provider: str, raw_keys: str) -> KeyRing:
    """Return the process-wide ring for ``provider``, building it on first use.

    Shared rather than per-``LLMClient`` because cooldowns must outlive a single request: an
    ``LLMClient`` is constructed per call site, so a per-instance ring would forget that a key
    was spent and re-try it on every request.

    Rebuilds if the configured key set changes (settings reload in tests).
    """
    existing = _RINGS.get(provider)
    if existing is not None and existing.all_keys() == KeyRing.from_csv(
        provider, raw_keys
    ).all_keys():
        return existing
    ring = KeyRing.from_csv(provider, raw_keys)
    _RINGS[provider] = ring
    return ring


def reset_keyrings() -> None:
    """Drop all cached rings (test hook)."""
    _RINGS.clear()


def is_quota_exhausted(exc: BaseException) -> bool:
    """True if an exception means the *key* is spent (so rotating to another key helps).

    Checks the HTTP status first (402 Payment Required is unambiguous), then falls back to
    provider phrasing. A 429 is deliberately NOT treated as exhaustion — that is throttling,
    handled by the shorter rate-limit cooldown.
    """
    status = getattr(exc, "status_code", None)
    if status == 402:
        return True
    text = str(exc).lower()
    return any(hint in text for hint in _EXHAUSTED_HINTS)
