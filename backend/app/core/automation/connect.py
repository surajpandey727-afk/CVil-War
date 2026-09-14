"""Interactive login capture: the user signs in, CVil-War keeps the session.

The question this answers is "how can the agent apply on my behalf if it has no credentials?"
The answer is that it never gets credentials. A headed browser opens on the platform's own
login page, the operator types their password into that real page, and when they are through
the resulting ``storage_state`` — cookies and origin storage, not credentials — is captured
and encrypted at rest by :class:`CredentialStore`.

Three properties hold by construction, and the tests pin all three:

* **No password ever reaches this process.** Nothing here reads keystrokes, renders a password
  field, or accepts a password argument. There is no code path that could.
* **Headed only.** A capture the operator cannot see is a capture they cannot consent to, so a
  headless launch is refused rather than silently downgraded.
* **Only the target's own cookies are kept.** A browser profile signed into one site is
  routinely signed into a dozen; storing all of them would turn "connect LinkedIn" into a
  credential vacuum. Everything off-domain is dropped before the state is persisted.

What this deliberately does not do is defeat anti-bot measures. If a platform challenges the
login, the operator answers it in the window themselves — that is the whole point of driving a
visible browser rather than impersonating one.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog

from app.core.job_discovery.source_registry import (
    BY_KEY,
    AccessMechanism,
    MechanismState,
    SourceSpec,
)

logger = structlog.get_logger(__name__)


def get_source(platform: str) -> SourceSpec | None:
    """Registry lookup by key, tolerant of the aliases the catalogue declares."""
    key = platform.strip().lower()
    if key in BY_KEY:
        return BY_KEY[key]
    return next((s for s in BY_KEY.values() if key in s.aliases), None)


#: How long a window stays open waiting for the operator. Long enough for a password manager,
#: a two-factor prompt and a misplaced phone; short enough that a forgotten window closes.
LOGIN_TIMEOUT = timedelta(minutes=10)

#: How often the watcher checks whether the sign-in has completed.
POLL_INTERVAL = 2.0


class ConnectState(StrEnum):
    """Where an in-flight capture has got to."""

    OPENING = "opening"              # launching the browser
    AWAITING_LOGIN = "awaiting_login"  # window is up, operator is signing in
    CAPTURING = "capturing"          # signed in, persisting the session
    CONNECTED = "connected"          # done
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def terminal(self) -> bool:
        return self in {
            ConnectState.CONNECTED,
            ConnectState.FAILED,
            ConnectState.CANCELLED,
            ConnectState.TIMED_OUT,
        }


@dataclass(frozen=True)
class LoginTarget:
    """Where to send the operator, and how to tell that they arrived.

    Declared as data rather than as a branch per platform: adding a portal is a row here, not
    a new code path. ``auth_cookies`` is a hint, not a requirement — when a platform is not
    listed the capture still works, falling back to "any durable cookie on the platform's own
    domain", which is what a completed sign-in actually leaves behind.
    """

    login_url: str
    #: Cookie names that specifically indicate an authenticated session, when known. Checked
    #: first because they are unambiguous; absence of a hint is not absence of a session.
    auth_cookies: tuple[str, ...] = ()
    #: Extra domains whose cookies belong to this login (SSO hosts, regional variants).
    extra_domains: tuple[str, ...] = ()
    #: Shown in the UI so the operator knows what they are being asked to do.
    instructions: str = ""


#: Login targets, keyed by source-registry key. The domain itself comes from the registry, so
#: it cannot drift from what discovery uses.
LOGIN_TARGETS: dict[str, LoginTarget] = {
    "linkedin": LoginTarget(
        login_url="https://www.linkedin.com/login",
        auth_cookies=("li_at",),
        extra_domains=("www.linkedin.com",),
        instructions=(
            "Sign in to LinkedIn as you normally would, including any verification code. "
            "Once your feed loads, this window closes on its own."
        ),
    ),
    "indeed": LoginTarget(
        login_url="https://secure.indeed.com/auth",
        auth_cookies=("SHOE", "CTK"),
        extra_domains=("secure.indeed.com", "uk.indeed.com", "www.indeed.com"),
        instructions="Sign in to Indeed. Once your account page loads, this window closes.",
    ),
    "glassdoor": LoginTarget(
        login_url="https://www.glassdoor.co.uk/profile/login_input.htm",
        auth_cookies=("GDSession",),
        extra_domains=("www.glassdoor.co.uk", "www.glassdoor.com"),
        instructions="Sign in to Glassdoor. Once you are back on the site, this window closes.",
    ),
    "wellfound": LoginTarget(
        login_url="https://wellfound.com/login",
        auth_cookies=("_wellfound",),
        extra_domains=("www.wellfound.com",),
        instructions="Sign in to Wellfound. Once your profile loads, this window closes.",
    ),
    "reed": LoginTarget(
        login_url="https://www.reed.co.uk/account/signin",
        extra_domains=("www.reed.co.uk",),
        instructions="Sign in to Reed. Once your account page loads, this window closes.",
    ),
    "civilservice": LoginTarget(
        login_url="https://www.civilservicejobs.service.gov.uk/csr/index.cgi",
        extra_domains=("www.civilservicejobs.service.gov.uk",),
        instructions=(
            "This site shows a \"Quick check needed\" verification page before anything "
            "else — complete it yourself here, the same as any real visitor would, then "
            "sign in (or just browse) normally. Once you're through, this window closes."
        ),
    ),
    "ukvisajobs": LoginTarget(
        login_url="https://my.ukvisajobs.com/login",
        extra_domains=("my.ukvisajobs.com", "www.ukvisajobs.com"),
        instructions=(
            "Sign in to UK Visa Jobs. The real job catalogue lives behind this login — once "
            "your account page loads, this window closes."
        ),
    ),
    "findajob": LoginTarget(
        login_url="https://www.gov.uk/find-a-job",
        extra_domains=("jobs.service.gov.uk", "www.gov.uk"),
        instructions=(
            "This is DWP's new \"Work Hub\" service. Sign in (or create an account) as you "
            "normally would — it may ask you to verify or accept cookies first, same as any "
            "real visitor. Once you're signed in, this window closes on its own."
        ),
    ),
}

#: Cookies that are present whether or not anyone is signed in. Used only by the fallback
#: check, so that "the page set a consent cookie" is never mistaken for "the operator is in".
_NON_AUTH_COOKIES = frozenset({
    "lang", "bcookie", "bscookie", "lidc", "jsessionid", "li_gc", "li_alerts",
    "guest_id", "consent", "cookieconsent", "gdpr", "optanonconsent", "onetrustconsent",
    "_ga", "_gid", "_gcl_au", "_fbp", "datadome", "cf_clearance", "csrftoken", "xsrf-token",
})


def connectable(platform: str) -> bool:
    """Whether this platform is one an operator can connect a browser session for.

    Driven by the registry's mechanism ladder rather than by a second hand-maintained list:
    a portal is connectable when it declares an authenticated-browser rung that is not
    unsupported. That keeps this honest as the ladder is probed and updated.
    """
    spec = get_source(platform)
    if spec is None:
        return False
    if platform in LOGIN_TARGETS:
        return True
    return spec.mechanism(AccessMechanism.AUTHENTICATED_BROWSER) in {
        MechanismState.AVAILABLE,
        MechanismState.AUTH_REQUIRED,
    }


def target_for(platform: str) -> LoginTarget | None:
    """The login target for a platform, synthesised from the registry when not declared."""
    if platform in LOGIN_TARGETS:
        return LOGIN_TARGETS[platform]
    spec = get_source(platform)
    if spec is None or not spec.domain:
        return None
    # A portal with an authenticated-browser rung but no declared login page: send the operator
    # to the site itself and let the fallback cookie check decide. Better than refusing.
    return LoginTarget(
        login_url=f"https://{spec.domain}",
        instructions=f"Sign in to {spec.label} in the window, then return here.",
    )


def domains_for(platform: str) -> frozenset[str]:
    """Every hostname whose cookies belong to this platform's login."""
    spec = get_source(platform)
    domains: set[str] = set()
    if spec is not None and spec.domain:
        domains.add(spec.domain.lower())
    target = LOGIN_TARGETS.get(platform)
    if target:
        domains.update(d.lower() for d in target.extra_domains)
    return frozenset(domains)


def _cookie_domain_matches(cookie_domain: str, domains: frozenset[str]) -> bool:
    """True when a cookie belongs to one of the platform's own hosts.

    Suffix matching is anchored on a dot so that ``notlinkedin.com`` cannot pass as
    ``linkedin.com`` — the check that stops a look-alike host donating cookies to a session.
    """
    host = cookie_domain.lstrip(".").lower()
    return any(host == d or host.endswith(f".{d}") for d in domains)


def filter_storage_state(
    storage_state: dict[str, Any], domains: frozenset[str]
) -> dict[str, Any]:
    """Strip everything that is not the target platform's own session.

    The operator connecting LinkedIn has consented to CVil-War holding their LinkedIn session,
    and to nothing else. A shared browser profile carries far more than that, so origins and
    cookies outside the platform are discarded here rather than encrypted and kept.
    """
    cookies = [
        c for c in storage_state.get("cookies", [])
        if _cookie_domain_matches(str(c.get("domain", "")), domains)
    ]
    origins = [
        o for o in storage_state.get("origins", [])
        if _cookie_domain_matches(
            str(o.get("origin", "")).removeprefix("https://").removeprefix("http://"), domains
        )
    ]
    return {"cookies": cookies, "origins": origins}


def signed_in(storage_state: dict[str, Any], platform: str) -> bool:
    """Whether the captured state represents a completed sign-in.

    Two rungs, for the same reason the rest of the system has them: a declared auth-cookie name
    is decisive when present, and when it is not, a durable first-party cookie that is not a
    known consent or analytics cookie is the best available evidence. Guessing "signed in" too
    eagerly would store a useless session and report success, so the fallback excludes the
    cookies every visitor gets.
    """
    domains = domains_for(platform)
    cookies = [
        c for c in storage_state.get("cookies", [])
        if _cookie_domain_matches(str(c.get("domain", "")), domains)
    ]
    if not cookies:
        return False

    target = LOGIN_TARGETS.get(platform)
    if target and target.auth_cookies:
        wanted = {name.lower() for name in target.auth_cookies}
        return any(str(c.get("name", "")).lower() in wanted and c.get("value") for c in cookies)

    return any(
        str(c.get("name", "")).lower() not in _NON_AUTH_COOKIES and c.get("value")
        for c in cookies
    )


@dataclass
class ConnectAttempt:
    """One interactive capture, from window-open to stored session."""

    id: str
    user_id: str
    platform: str
    state: ConnectState = ConnectState.OPENING
    detail: str = ""
    instructions: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + LOGIN_TIMEOUT
    )
    #: Set when the operator cancels; the watcher checks it between polls.
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def seconds_remaining(self) -> int:
        return max(0, int((self.expires_at - datetime.now(UTC)).total_seconds()))


def _earliest_expiry(storage_state: dict[str, Any]) -> datetime | None:
    """When the session stops being usable, taken from the cookies themselves.

    The soonest-expiring cookie decides, because the session dies with it. A guessed fixed
    window would either promise a session that has already lapsed or keep prompting to
    reconnect one that is still perfectly good.
    """
    stamps = [
        float(c["expires"]) for c in storage_state.get("cookies", [])
        if isinstance(c.get("expires"), (int, float)) and float(c["expires"]) > 0
    ]
    if not stamps:
        return None
    return datetime.fromtimestamp(min(stamps), tz=UTC)


class ConnectManager:
    """Tracks in-flight capture attempts and drives the browser for each.

    Attempts live in memory on purpose. A half-finished login is not durable state — the
    browser window it refers to dies with the process, so persisting the attempt would only
    resurrect a reference to a window that no longer exists. What *is* durable, the captured
    session, goes to encrypted storage via :mod:`app.services.platform_session`.
    """

    def __init__(self) -> None:
        self._attempts: dict[str, ConnectAttempt] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def get(self, attempt_id: str, user_id: str) -> ConnectAttempt | None:
        """One attempt, scoped to its owner so an id cannot be read across accounts."""
        attempt = self._attempts.get(attempt_id)
        return attempt if attempt and attempt.user_id == user_id else None

    def active_for(self, user_id: str, platform: str) -> ConnectAttempt | None:
        """A capture already running for this platform, if any."""
        return next(
            (
                a for a in self._attempts.values()
                if a.user_id == user_id and a.platform == platform and not a.state.terminal
            ),
            None,
        )

    def cancel(self, attempt_id: str, user_id: str) -> bool:
        """Ask a capture to stop. The watcher closes the browser at its next poll."""
        attempt = self.get(attempt_id, user_id)
        if attempt is None or attempt.state.terminal:
            return False
        attempt.cancelled.set()
        return True

    def prune(self) -> None:
        """Drop finished attempts so a long-lived process does not accumulate them."""
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        for key in [
            k for k, a in self._attempts.items() if a.state.terminal and a.started_at < cutoff
        ]:
            self._attempts.pop(key, None)
            self._tasks.pop(key, None)

    def start(self, user_id: str, platform: str) -> ConnectAttempt:
        """Open a login window and begin watching for a completed sign-in."""
        self.prune()
        platform = platform.strip().lower()

        existing = self.active_for(user_id, platform)
        if existing is not None:
            # Two clicks on Connect must not open two windows onto the same login.
            return existing

        target = target_for(platform)
        if target is None:
            raise ValueError(
                f"'{platform}' is not a portal a browser session can be connected for"
            )

        attempt = ConnectAttempt(
            id=str(uuid.uuid4()),
            user_id=user_id,
            platform=platform,
            instructions=target.instructions,
        )
        self._attempts[attempt.id] = attempt
        self._tasks[attempt.id] = asyncio.create_task(self._run(attempt, target))
        logger.info("connect_started", user_id=user_id, platform=platform, attempt=attempt.id)
        return attempt

    async def _run(self, attempt: ConnectAttempt, target: LoginTarget) -> None:
        """Drive one capture. Never raises — failure is reported on the attempt instead."""
        try:
            await self._drive(attempt, target)
        except asyncio.CancelledError:
            attempt.state = ConnectState.CANCELLED
            attempt.detail = "The connection was cancelled."
            raise
        except Exception as exc:
            attempt.state = ConnectState.FAILED
            attempt.detail = str(exc)[:400] or exc.__class__.__name__
            logger.warning(
                "connect_failed", platform=attempt.platform, attempt=attempt.id, error=str(exc)
            )

    async def _drive(self, attempt: ConnectAttempt, target: LoginTarget) -> None:
        """Open the window, wait for the operator, then capture and store the session."""
        from playwright.async_api import async_playwright

        domains = domains_for(attempt.platform)

        async with async_playwright() as pw:
            # Headed, always. A capture the operator cannot watch is one they cannot consent
            # to, and they must be able to answer a verification prompt themselves.
            browser = await pw.chromium.launch(headless=False)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(target.login_url, wait_until="domcontentloaded")

                attempt.state = ConnectState.AWAITING_LOGIN
                logger.info("connect_awaiting_login", platform=attempt.platform)

                state: dict[str, Any] | None = None
                while datetime.now(UTC) < attempt.expires_at:
                    if attempt.cancelled.is_set():
                        attempt.state = ConnectState.CANCELLED
                        attempt.detail = "Cancelled before sign-in completed."
                        return
                    if not context.pages:
                        # The operator closed the window. That is a decision, not a fault.
                        attempt.state = ConnectState.CANCELLED
                        attempt.detail = "The login window was closed before sign-in completed."
                        return

                    current = await context.storage_state()
                    if signed_in(current, attempt.platform):
                        state = current
                        break
                    await asyncio.sleep(POLL_INTERVAL)

                if state is None:
                    attempt.state = ConnectState.TIMED_OUT
                    attempt.detail = (
                        "No completed sign-in was detected within "
                        f"{int(LOGIN_TIMEOUT.total_seconds() // 60)} minutes."
                    )
                    return

                attempt.state = ConnectState.CAPTURING
                # Everything outside the platform's own hosts is dropped before this leaves
                # the browser boundary — connecting one portal must not capture the others.
                scoped = filter_storage_state(state, domains)
            finally:
                await browser.close()

        await self._persist(attempt, scoped)

    async def _persist(self, attempt: ConnectAttempt, storage_state: dict[str, Any]) -> None:
        """Hand the captured session to encrypted storage."""
        from app.db.session import get_session_factory
        from app.services import platform_session as service

        session_factory = get_session_factory()
        async with session_factory() as db:
            await service.import_session(
                db, attempt.user_id, attempt.platform, storage_state,
                expires_at=_earliest_expiry(storage_state),
            )

        attempt.state = ConnectState.CONNECTED
        attempt.detail = (
            f"Connected. {len(storage_state.get('cookies', []))} session cookies for "
            f"{attempt.platform} were stored, encrypted. No password was seen or kept."
        )
        logger.info("connect_succeeded", platform=attempt.platform, attempt=attempt.id)


#: Process-wide manager, matching how the rest of the automation holds browser state.
MANAGER = ConnectManager()
