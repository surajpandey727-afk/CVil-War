"""Platform management: the registry joined to this user's connections.

One assembler, so the Sources screen and the Settings platform section read the same thing.
They previously maintained separate lists — Settings hard-coded four platforms while the
registry served fifty-five — which is how a product ends up saying "Reed: connected" on one
screen and "Reed: not connected" on another.

Actions are decided here rather than in the UI, because availability depends on facts the
frontend does not have: whether an adapter exists, whether the source needs a login at all,
and what state the stored session is in. A disabled action with a stated reason is more
useful than a button that silently does nothing.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from time import perf_counter

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.automation.platforms.registry import platform_registry
from app.core.job_discovery.source_registry import (
    ALL_SOURCES,
    BY_KEY,
    SourceHealth,
    SourceSpec,
    health_for,
)
from app.models.enums import SessionState
from app.models.platform_session import PlatformSession
from app.models.user_settings import UserSettings
from app.schemas.platforms import (
    PlatformAction,
    PlatformsResponse,
    PlatformStatus,
    PlatformTestResponse,
    PlatformTestResult,
)
from app.services.evidence import mask_account

logger = structlog.get_logger(__name__)

#: Session states in which the account can actually be used. Kept identical to the evidence
#: panel's definition — two places disagreeing about "connected" is the defect this module
#: exists to prevent.
_USABLE = (SessionState.SESSION_ACTIVE, SessionState.SESSION_EXPIRING)

#: Health values meaning the source can serve results right now.
_WORKING = (SourceHealth.LIVE, SourceHealth.AUTH_REQUIRED)


def _capabilities(key: str) -> list[str]:
    """What this adapter says it can do, asked of the adapter itself.

    Read from the live registry rather than a table kept alongside it, so a capability added
    to an adapter shows up here without a second edit.
    """
    if not platform_registry.has(key):
        return []
    try:
        adapter = platform_registry.create(key)
        caps = adapter.capabilities()
    except Exception as exc:  # a broken adapter must not take the settings page down
        logger.warning("platforms.capabilities_failed", key=key, error=str(exc))
        return []
    return sorted(name for name, enabled in caps.items() if enabled and name != "needs_credential")


def _needs_credential(key: str) -> bool:
    """Whether a login/session is the right next step for this source.

    Checked two ways, because either one alone missed real cases: the adapter's own
    declared capability answers for sources that already have one, but a source the
    registry has confirmed needs a browser session (``civilservice``, ``ukvisajobs`` —
    verified live, not guessed) has no adapter yet precisely *because* nothing can be
    built until that session exists. Asking only the adapter reported "no login needed"
    for exactly the two sources sitting behind a login page — the Connect button never
    appeared, so there was no way to take the one human step that unblocks them.
    """
    from app.core.automation.connect import connectable

    if connectable(key):
        return True
    if not platform_registry.has(key):
        return False
    try:
        return bool(platform_registry.create(key).capabilities().get("needs_credential"))
    except Exception:
        return False


def _actions(
    *, implemented: bool, needs_login: bool, connected: bool, health: SourceHealth
) -> list[PlatformAction]:
    """Which controls to offer, and why one is unavailable when it is."""
    actions: list[PlatformAction] = []

    actions.append(PlatformAction(
        key="toggle",
        label="Enable for discovery",
        available=implemented,
        reason="" if implemented else "No adapter can serve this source yet.",
    ))

    if needs_login:
        actions.append(PlatformAction(
            key="connect",
            label="Reconnect" if connected else "Connect",
            available=True,
        ))
        actions.append(PlatformAction(
            key="disconnect",
            label="Disconnect",
            available=connected,
            reason="" if connected else "Nothing is connected for this platform.",
        ))
    else:
        # Saying so beats hiding the control: an operator looking for a login on a keyless
        # public API should learn that none is needed.
        actions.append(PlatformAction(
            key="connect",
            label="Connect",
            available=False,
            reason="This source is a public API and needs no login.",
        ))

    actions.append(PlatformAction(
        key="test",
        label="Test",
        available=implemented and health in _WORKING,
        reason="" if implemented and health in _WORKING
        else "Nothing to test until an adapter can reach this source.",
    ))
    return actions


async def list_platforms(db: AsyncSession, user_id: str) -> PlatformsResponse:
    """Every catalogued source, with this user's enablement and connection state."""
    sessions = {
        row.platform: row
        for row in (
            await db.execute(
                select(PlatformSession).where(PlatformSession.user_id == user_id)
            )
        ).scalars().all()
    }

    settings = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    enabled_keys = set(settings.platforms_enabled or []) if settings else set()

    statuses: list[PlatformStatus] = []
    for spec in ALL_SOURCES:
        health = health_for(spec)
        implemented = platform_registry.has(spec.key)
        session = sessions.get(spec.key)
        needs_login = _needs_credential(spec.key) or spec.api_key_field is not None
        connected = bool(session and session.state in _USABLE)

        statuses.append(PlatformStatus(
            key=spec.key,
            label=spec.label,
            tier=str(spec.tier),
            health=str(health),
            implemented=implemented,
            needs_credential=needs_login,
            capabilities=_capabilities(spec.key),
            enabled=spec.key in enabled_keys,
            connected=connected,
            connection_state=str(session.state) if session else "not_connected",
            # Masked on read as well as on write, so a row stored by an older build cannot
            # leak a full address through this endpoint.
            account=mask_account(session.account_label) if session else None,
            last_used_at=session.last_used_at if session else None,
            expires_at=session.expires_at if session else None,
            detail=session.state_detail if session else None,
            # Distinct from "no error": a source never exercised has nothing to report, and
            # showing a reassuring blank would be a claim nobody checked.
            last_error=spec.known_broken or spec.blocked_reason,
            actions=_actions(
                implemented=implemented,
                needs_login=needs_login,
                connected=connected,
                health=health,
            ),
        ))

    return PlatformsResponse(
        platforms=statuses,
        total=len(statuses),
        usable=sum(1 for s in statuses if s.implemented),
        connected=sum(1 for s in statuses if s.connected),
    )


#: Cap on concurrent probes. Each one is a real upstream request; running fifty at once would
#: be indistinguishable from an attack and would earn a rate limit from several of them.
_TEST_CONCURRENCY = 6
#: Per-probe ceiling. A source that has not answered in this long has answered the question.
_TEST_TIMEOUT = 25.0


async def test_platforms(
    db: AsyncSession, user_id: str, keys: Sequence[str] | None = None
) -> PlatformTestResponse:
    """Probe each source for real and report what actually happened.

    The Settings screen has always rendered a "Test" control that no endpoint served, so the
    operator could see a catalogue of fifty-five sources and had no way to establish whether
    any of them worked. This runs each adapter's own ``health_check`` — a live request, not a
    reading of the catalogue — so "live" means it answered a moment ago.

    Probes are bounded and run in parallel; one hanging source must not hold up the sweep.
    """
    started = perf_counter()
    registry = platform_registry
    available = {
        key: spec for key, spec in BY_KEY.items()
        if registry.has(key) and (not keys or key in set(keys))
    }
    semaphore = asyncio.Semaphore(_TEST_CONCURRENCY)

    async def probe(key: str, spec: SourceSpec) -> PlatformTestResult:
        began = perf_counter()
        async with semaphore:
            try:
                # ``create`` instantiates; ``get`` returns the class, which has no
                # bound health_check to await.
                adapter = registry.create(key)
                state, detail = await asyncio.wait_for(
                    adapter.health_check(), timeout=_TEST_TIMEOUT
                )
            except TimeoutError:
                state, detail = "unavailable", f"No answer within {_TEST_TIMEOUT:.0f}s"
            except Exception as exc:
                state, detail = "unavailable", str(exc)[:200] or exc.__class__.__name__
        # "N returned" is health_check's own phrasing; pull the count back out for the UI.
        count = 0
        if match := re.match(r"(\d+)\s+returned", detail):
            count = int(match.group(1))
        return PlatformTestResult(
            key=key,
            label=spec.label,
            state=state,
            detail=detail,
            results=count,
            elapsed_ms=int((perf_counter() - began) * 1000),
            ok=state == "live",
        )

    results = await asyncio.gather(*(probe(k, s) for k, s in available.items()))
    ordered = sorted(results, key=lambda r: (r.ok is False, r.label.lower()))
    logger.info(
        "platforms_tested", user_id=user_id, tested=len(ordered),
        passed=sum(1 for r in ordered if r.ok),
    )
    return PlatformTestResponse(
        results=ordered,
        tested=len(ordered),
        passed=sum(1 for r in ordered if r.ok),
        failed=sum(1 for r in ordered if not r.ok),
        elapsed_ms=int((perf_counter() - started) * 1000),
    )
