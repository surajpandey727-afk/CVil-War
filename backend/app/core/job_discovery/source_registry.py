"""The job-source catalogue and its live health.

Two things live here, deliberately together:

* **The catalogue** — every source the product knows about, grouped into the tiers the
  operator reasons about (must-use boards, UK boards, public sector, tech/startup,
  specialist recruiters, and directly-monitored company career pages).
* **Health** — whether each one can actually return results right now.

Why a catalogue that includes sources with no adapter: hiding them is what produced the old
failure mode, where a search across "all platforms" returned nothing and the UI reported a
neutral "No matching roles" for what was really an unbuilt or dead integration. A source with
``implemented=False`` is shown, labelled, and excluded from the fan-out — an honest gap beats
a silent one.

Health is derived, not stored:

* ``not_implemented`` — no adapter is registered under this key.
* ``auth_required``  — an adapter exists but its credential or API key is unset.
* ``degraded``       — registered, but known-broken (the browser-use platforms; B14 in
  ``docs/PHASE0_AUDIT.md``).
* ``live``           — registered and usable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from app.config.settings import get_settings


class SourceTier(StrEnum):
    """Grouping used by the UI's source rail and Sources screen.

    No TIER3: removed by explicit operator request (2026-08-30) along with every catalogue
    entry that was in it (Civil Service Jobs and UK Visa Jobs moved to TIER2 — they are two
    of the operator's own explicitly-requested sources; NHS Jobs, TRAC and Digital & Data
    Jobs were dropped outright, having no adapter and no path to one). Kept as a documented
    gap rather than renumbering TIER4/5, which would silently reclassify every source in them.
    """

    TIER1 = "tier1"
    TIER2 = "tier2"
    TIER4 = "tier4"
    TIER5 = "tier5"
    CAREERS = "careers"


TIER_LABELS: dict[SourceTier, tuple[str, str]] = {
    SourceTier.TIER1: ("Tier 1 — Must use", "Highest volume for London AI/ML and product roles"),
    SourceTier.TIER2: ("Tier 2 — UK job boards", "Consultancies, traditional business, contract"),
    SourceTier.TIER4: ("Tier 4 — Tech & startup", "AI-first companies and scale-ups"),
    SourceTier.TIER5: ("Tier 5 — Specialist recruiters", "Registered agencies"),
    SourceTier.CAREERS: ("Company career pages", "Monitored directly, checked hourly"),
}


class SourceHealth(StrEnum):
    LIVE = "live"
    DEGRADED = "degraded"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    #: Server-side automation is blocked, but the portal is reachable by a user-authorised
    #: browser session. This is NOT "unavailable" — it is a different rung of the ladder.
    INTERACTIVE_AVAILABLE = "interactive_available"
    UNAVAILABLE = "unavailable"
    NOT_IMPLEMENTED = "not_implemented"


class AccessMechanism(StrEnum):
    """How a portal can be reached, best capability first.

    A portal is resolved per-mechanism, not as a single verdict. Treating one rejected HTTP
    request as "portal unavailable" is the specific error this exists to prevent: a site can
    block server-side automation outright and still be perfectly usable through the ordinary
    browser session the candidate is already entitled to use.
    """

    API = "api"                                    # official, documented
    PUBLIC_ENDPOINT = "public_endpoint"            # keyless JSON/ATS board
    FEED = "feed"                                  # RSS/Atom
    PUBLIC_WEBSITE = "public_website"              # server-rendered, automation permitted
    AUTHENTICATED_BROWSER = "authenticated_browser"  # user-authorised persistent session
    INTERACTIVE_BROWSER = "interactive_browser"    # user drives, system assists
    APPLICATION_URL = "application_url"            # hand off a deep link
    STATUS_SYNC = "status_sync"                    # read application state only
    HUMAN = "human"                                # entirely manual


class MechanismState(StrEnum):
    """Whether one mechanism is usable for one portal right now."""

    AVAILABLE = "available"
    BLOCKED = "blocked"            # upstream refuses automation (403/anti-bot)
    AUTH_REQUIRED = "auth_required"
    UNKNOWN = "unknown"            # never probed — not the same as unavailable
    UNSUPPORTED = "unsupported"    # the portal has no such mechanism


@dataclass(frozen=True)
class SourceSpec:
    """A catalogue entry. ``key`` is the value stored on ``Job.platform``."""

    key: str
    label: str
    domain: str
    tier: SourceTier
    #: True when an adapter is registered under ``key``.
    implemented: bool = False
    #: Name of the settings attribute holding this source's API key, if it needs one.
    api_key_field: str | None = None
    #: Set when the adapter exists but is known not to work.
    known_broken: str | None = None
    #: Why server-side automation is refused, when it is. This blocks the API/public-endpoint
    #: rungs of the ladder — it does NOT condemn the portal, which may still be fully usable
    #: through an authorised browser session.
    blocked_reason: str | None = None
    #: Per-mechanism availability. Anything unlisted is UNKNOWN — never probed, which is not
    #: the same as unavailable and must not be reported as such.
    mechanisms: dict[AccessMechanism, MechanismState] = field(default_factory=dict)
    note: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def mechanism(self, kind: AccessMechanism) -> MechanismState:
        """State of one mechanism, defaulting to UNKNOWN rather than assuming failure."""
        return self.mechanisms.get(kind, MechanismState.UNKNOWN)

    def best_mechanism(self) -> AccessMechanism | None:
        """Highest-capability mechanism currently available, or None.

        Order is the resolution ladder: prefer an official API, fall back through public
        endpoints and feeds, then a user-authorised browser, then an interactive workflow,
        and finally handing over a link. Escalation happens because the rung above is
        genuinely unavailable — never because one request was rejected.
        """
        for kind in AccessMechanism:
            if self.mechanism(kind) is MechanismState.AVAILABLE:
                return kind
        return None


_BROKEN_SCRAPER = "Browser scraper offline — targets a removed browser-use API (B14)"

CATALOGUE: tuple[SourceSpec, ...] = (
    # Tier 1 — registered browser platforms, currently non-functional.
    # Discovery reads the public listing, which needs no account and puts nothing at risk;
    # the connected session is reserved for applying, where it is genuinely required.
    SourceSpec(
        "linkedin", "LinkedIn Jobs", "linkedin.com", SourceTier.TIER1, True,
        mechanisms={
            AccessMechanism.PUBLIC_WEBSITE: MechanismState.AVAILABLE,
            AccessMechanism.AUTHENTICATED_BROWSER: MechanismState.AUTH_REQUIRED,
        },
        note="Public listing for discovery; a connected session is needed only to apply.",
    ),
    SourceSpec(
        "indeed", "Indeed UK", "indeed.co.uk", SourceTier.TIER1, True, known_broken=_BROKEN_SCRAPER
    ),
    SourceSpec(
        "glassdoor", "Glassdoor", "glassdoor.co.uk", SourceTier.TIER1, True,
        known_broken=_BROKEN_SCRAPER,
    ),
    SourceSpec("wellfound", "Wellfound", "wellfound.com", SourceTier.TIER1),

    # The keyless API sources that work today.
    SourceSpec("remotive", "Remotive", "remotive.com", SourceTier.TIER4, True),
    SourceSpec("jobicy", "Jobicy", "jobicy.com", SourceTier.TIER4, True),
    SourceSpec("arbeitnow", "Arbeitnow", "arbeitnow.com", SourceTier.TIER4, True),
    SourceSpec("remoteok", "RemoteOK", "remoteok.com", SourceTier.TIER4, True),
    SourceSpec(
        "exa", "Exa semantic search", "exa.ai", SourceTier.TIER4, True, api_key_field="exa_api_key"
    ),

    SourceSpec(
        "reed", "Reed", "reed.co.uk", SourceTier.TIER2, True, api_key_field="reed_api_key",
    ),
    SourceSpec(
        "movejobs", "MoveJobs", "movejobs.uk", SourceTier.TIER2, True,
        mechanisms={AccessMechanism.PUBLIC_WEBSITE: MechanismState.AVAILABLE},
        note="Visa-sponsorship-framed UK board; server-side keyword search confirmed live.",
    ),
    SourceSpec(
        "tarve", "Tarve", "tarve.co.uk", SourceTier.TIER2, True,
        mechanisms={AccessMechanism.PUBLIC_WEBSITE: MechanismState.AVAILABLE},
        note=(
            "UK board that cross-checks postings against the Home Office Skilled Worker "
            "sponsor register itself — a second, independent signal alongside this system's "
            "own core.sponsorship check."
        ),
    ),
    SourceSpec(
        "workinstartups", "WorkInStartups", "workinstartups.com", SourceTier.TIER2,
        mechanisms={
            AccessMechanism.PUBLIC_WEBSITE: MechanismState.BLOCKED,
        },
        blocked_reason=(
            "Confirmed (its own footer) to be part of the Adzuna network, and Cloudflare-"
            "protected against direct HTTP scraping (verified 2026-08-29)."
        ),
        note=(
            "Covered via the Adzuna source instead — same data, already a working keyed "
            "adapter (confirmed live 2026-08-30: a real Adzuna API call with the configured "
            "key returned real UK results)."
        ),
    ),
    SourceSpec(
        "adzuna", "Adzuna", "adzuna.co.uk", SourceTier.TIER2, True,
        api_key_field="adzuna_app_key", note="Live — app id configured.",
    ),
    SourceSpec(
        "findajob", "Work Hub — GOV.UK", "jobs.service.gov.uk", SourceTier.TIER2,
        blocked_reason=(
            "DWP's jobseeker service moved to a new platform (jobs.service.gov.uk, "
            "'Work Hub' — replaces the old findajob.dwp.gov.uk) sometime before "
            "2026-08-30; it is new enough that its own banner still says 'This is a new "
            "service'. Live reconnaissance of its job-search page structure was attempted "
            "but blocked by a tooling/network issue this session (not a site-side block) — "
            "the homepage itself loaded fine in a real browser, so this is likely buildable, "
            "just not yet verified."
        ),
        note="Follow-up: retry reconnaissance, then adapt if the listings are keylessly reachable.",
    ),

    # Tier 2 entries that need the operator's own one-time login before anything can be
    # built against them — the Connect flow (core.automation.connect) already supports both;
    # what's missing is the discovery adapter that would consume the resulting session, which
    # cannot be written correctly before that session exists to inspect.
    SourceSpec(
        "civilservice", "Civil Service Jobs", "civilservicejobs.service.gov.uk", SourceTier.TIER2,
        blocked_reason=(
            "Every page — including the base domain — serves a \"Quick check needed\" "
            "bot-verification gate before any content, confirmed live in a real browser "
            "(not just a scripted request). robots.txt allows crawling, but the gate itself "
            "cannot be automated through (verified 2026-08-29)."
        ),
        mechanisms={
            AccessMechanism.API: MechanismState.UNSUPPORTED,
            AccessMechanism.PUBLIC_ENDPOINT: MechanismState.UNSUPPORTED,
            AccessMechanism.PUBLIC_WEBSITE: MechanismState.BLOCKED,
            # A human passes the one-time check normally; the resulting session cookie can
            # then be reused for server-side requests — the same "assisted, then automated"
            # pattern already used for LinkedIn/Indeed's saved session.
            AccessMechanism.AUTHENTICATED_BROWSER: MechanismState.AUTH_REQUIRED,
            AccessMechanism.INTERACTIVE_BROWSER: MechanismState.AVAILABLE,
        },
        note="Connect this in Settings (the one-time human check), then discovery can be built.",
    ),
    SourceSpec(
        "ukvisajobs", "UK Visa Jobs", "ukvisajobs.com", SourceTier.TIER2,
        mechanisms={
            # The public homepage's "Featured Jobs" carry no real per-job URL (every link is
            # a client-side-routed placeholder) — nothing worth adapting sits on this rung.
            AccessMechanism.PUBLIC_WEBSITE: MechanismState.BLOCKED,
            AccessMechanism.AUTHENTICATED_BROWSER: MechanismState.AUTH_REQUIRED,
        },
        blocked_reason=(
            "The public homepage's job cards have no real per-job URL (placeholder "
            "href=\"/\", routed client-side) — the working catalogue with real links lives "
            "behind login on my.ukvisajobs.com (verified 2026-08-29)."
        ),
        note="Connect this in Settings (the one-time human login), then discovery can be built.",
    ),
)

#: Employers whose career pages are polled directly. Key format: ``careers:<slug>``.
#:
#: Every entry with a live board (see ``sources.ats.COMPANY_BOARDS``) was verified by calling
#: its actual Greenhouse/Lever/Ashby/SmartRecruiters endpoint, not guessed — a wrong token
#: silently returns zero jobs forever, so nothing here is assumed. Entries with no adapter yet
#: (NVIDIA, C3 AI, LSEG, Bloomberg, Capital One, Just Eat, Booking.com, Expedia, King) were
#: probed across all four providers and genuinely have none — see
#: ``sources.ats.NO_PUBLIC_BOARD`` — they stay listed, honestly labelled unimplemented, rather
#: than silently disappearing.
CAREER_PAGES: tuple[tuple[str, str, str], ...] = (
    ("deepmind", "DeepMind", "deepmind.google"),
    ("anthropic", "Anthropic", "anthropic.com"),
    ("openai", "OpenAI", "openai.com"),
    ("palantir", "Palantir", "palantir.com"),
    ("wayve", "Wayve", "wayve.ai"),
    ("isomorphic", "Isomorphic Labs", "isomorphiclabs.com"),
    ("nvidia", "NVIDIA", "nvidia.com"),
    ("c3ai", "C3 AI", "c3.ai"),
    ("revolut", "Revolut", "revolut.com"),
    ("wise", "Wise", "wise.com"),
    ("monzo", "Monzo", "monzo.com"),
    ("starling", "Starling Bank", "starlingbank.com"),
    ("lseg", "LSEG", "lseg.com"),
    ("bloomberg", "Bloomberg", "bloomberg.com"),
    ("lendable", "Lendable", "lendable.co.uk"),
    ("capitalone", "Capital One", "capitalone.co.uk"),
    ("deliveroo", "Deliveroo", "deliveroo.co.uk"),
    ("justeat", "Just Eat", "just-eat.co.uk"),
    ("ocado", "Ocado", "ocadogroup.com"),
    ("asos", "ASOS", "asos.com"),
    ("booking", "Booking.com", "booking.com"),
    ("spotify", "Spotify", "spotify.com"),
    ("expedia", "Expedia", "expedia.com"),
    ("trainline", "Trainline", "thetrainline.com"),
    ("king", "King", "king.com"),

    # Added 2026-08-30 — UK-headquartered and UK-hiring AI/data/fintech/product employers,
    # each with a live-verified board (see the date-stamped block in COMPANY_BOARDS above).
    ("quantexa", "Quantexa", "quantexa.com"),
    ("synthesia", "Synthesia", "synthesia.io"),
    ("speechmatics", "Speechmatics", "speechmatics.com"),
    ("faculty", "Faculty AI", "faculty.ai"),
    ("tractable", "Tractable", "tractable.ai"),
    ("graphcore", "Graphcore", "graphcore.ai"),
    ("improbable", "Improbable", "improbable.io"),
    ("gocardless", "GoCardless", "gocardless.com"),
    ("zopa", "Zopa", "zopa.com"),
    ("truelayer", "TrueLayer", "truelayer.com"),
    ("clearbank", "ClearBank", "clearbank.co.uk"),
    ("marshmallow", "Marshmallow", "marshmallow.com"),
    ("cleo", "Cleo", "cleo.com"),

    # Global remote-friendly AI/data/product employers that also hire UK-based roles.
    ("snowflake", "Snowflake", "snowflake.com"),
    ("databricks", "Databricks", "databricks.com"),
    ("datadog", "Datadog", "datadoghq.com"),
    ("fivetran", "Fivetran", "fivetran.com"),
    ("similarweb", "Similarweb", "similarweb.com"),
    ("contentsquare", "Contentsquare", "contentsquare.com"),
    ("alphasense", "AlphaSense", "alpha-sense.com"),
    ("stripe", "Stripe", "stripe.com"),
    ("notion", "Notion", "notion.so"),
    ("figma", "Figma", "figma.com"),
    ("canva", "Canva", "canva.com"),
    ("airtable", "Airtable", "airtable.com"),
    ("asana", "Asana", "asana.com"),
    ("miro", "Miro", "miro.com"),
    ("linear", "Linear", "linear.app"),
    ("vercel", "Vercel", "vercel.com"),
    ("gitlab", "GitLab", "gitlab.com"),
    ("thoughtworks", "Thoughtworks", "thoughtworks.com"),
    ("cohere", "Cohere", "cohere.com"),
    ("stabilityai", "Stability AI", "stability.ai"),
    ("elevenlabs", "ElevenLabs", "elevenlabs.io"),
    ("runwayml", "Runway", "runwayml.com"),
    ("perplexity", "Perplexity", "perplexity.ai"),
    ("scale", "Scale AI", "scale.com"),
    ("together", "Together AI", "together.ai"),
    ("harvey", "Harvey", "harvey.ai"),
    ("glean", "Glean", "glean.com"),
    ("ramp", "Ramp", "ramp.com"),
    ("brex", "Brex", "brex.com"),
    ("remote", "Remote", "remote.com"),
)

ALL_SOURCES: tuple[SourceSpec, ...] = CATALOGUE + tuple(
    SourceSpec(f"careers:{slug}", label, domain, SourceTier.CAREERS)
    for slug, label, domain in CAREER_PAGES
)

BY_KEY: dict[str, SourceSpec] = {spec.key: spec for spec in ALL_SOURCES}


def _has_api_key(field_name: str) -> bool:
    """True when the named API key is set to a non-empty value.

    Looks on the root ``Settings`` first, then the nested ``llm`` group. Both are needed:
    ``exa_api_key`` is a root field while the provider keys live under ``llm``. Checking only
    ``llm`` reported Exa as ``auth_required`` even with a key configured, because the attribute
    simply is not there — a silent misreport rather than an error.
    """
    settings = get_settings()
    for holder in (settings, settings.llm):
        secret = getattr(holder, field_name, None)
        if secret is None:
            continue
        getter = getattr(secret, "get_secret_value", None)
        return bool(getter() if callable(getter) else secret)
    return False


def _registered_keys() -> frozenset[str]:
    """Keys with a real adapter, read from the registry rather than a hand-kept flag.

    ``SourceSpec.implemented`` was maintained by hand and drifted the moment an adapter was
    added — the twelve employer ATS boards were all still marked unimplemented. Asking the
    registry makes the catalogue self-correcting.
    """
    try:
        from app.core.job_discovery.sources import IMPLEMENTED_KEYS

        return IMPLEMENTED_KEYS
    except Exception:  # pragma: no cover - import cycle / partial init
        return frozenset()


def health_for(spec: SourceSpec) -> SourceHealth:
    """Derive a source's current health from the best mechanism still open to it.

    A rejected HTTP request disqualifies *that mechanism*, not the portal. A site can refuse
    server-side automation and remain entirely usable through the browser session the
    candidate is already entitled to — reporting it UNAVAILABLE hides real, reachable jobs.
    """
    best = spec.best_mechanism()
    if spec.blocked_reason:
        # Server rungs are refused. Fall to whatever legitimate rung remains.
        if best in (AccessMechanism.INTERACTIVE_BROWSER, AccessMechanism.APPLICATION_URL):
            return SourceHealth.INTERACTIVE_AVAILABLE
        if spec.mechanism(AccessMechanism.AUTHENTICATED_BROWSER) is MechanismState.AUTH_REQUIRED:
            return SourceHealth.AUTH_REQUIRED
        return SourceHealth.UNAVAILABLE
    if not (spec.implemented or spec.key in _registered_keys()):
        return SourceHealth.NOT_IMPLEMENTED
    if spec.known_broken:
        # A dead scraper does not condemn the portal either: if the operator can sign in,
        # the interactive rung is still open.
        if best is AccessMechanism.INTERACTIVE_BROWSER:
            return SourceHealth.INTERACTIVE_AVAILABLE
        return SourceHealth.DEGRADED
    if spec.api_key_field:
        try:
            if not _has_api_key(spec.api_key_field):
                return SourceHealth.AUTH_REQUIRED
        except Exception:  # settings unavailable — report the honest unknown, not a crash
            return SourceHealth.AUTH_REQUIRED
    return SourceHealth.LIVE


def usable_keys(requested: Iterable[str] | None = None) -> list[str]:
    """Filter ``requested`` down to keys that can actually return results.

    ``services.job_search`` fans out over whatever it is given; passing it a key with no
    adapter costs a guaranteed-empty round trip and, worse, makes an empty result set look
    like a market signal. Call this first.
    """
    keys = list(requested) if requested is not None else list(BY_KEY)
    return [k for k in keys if (spec := BY_KEY.get(k)) and health_for(spec) is SourceHealth.LIVE]
