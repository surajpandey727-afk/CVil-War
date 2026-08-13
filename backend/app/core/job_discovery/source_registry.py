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
    """Grouping used by the UI's source rail and Sources screen."""

    TIER1 = "tier1"
    TIER2 = "tier2"
    TIER3 = "tier3"
    TIER4 = "tier4"
    TIER5 = "tier5"
    CAREERS = "careers"


TIER_LABELS: dict[SourceTier, tuple[str, str]] = {
    SourceTier.TIER1: ("Tier 1 — Must use", "Highest volume for London AI/ML and product roles"),
    SourceTier.TIER2: ("Tier 2 — UK job boards", "Consultancies, traditional business, contract"),
    SourceTier.TIER3: (
        "Tier 3 — Government & public sector",
        "Statistical Scientist, Operational Research, AI Specialist",
    ),
    SourceTier.TIER4: ("Tier 4 — Tech & startup", "AI-first companies and scale-ups"),
    SourceTier.TIER5: ("Tier 5 — Specialist recruiters", "Registered agencies"),
    SourceTier.CAREERS: ("Company career pages", "Monitored directly, checked hourly"),
}


class SourceHealth(StrEnum):
    LIVE = "live"
    DEGRADED = "degraded"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    NOT_IMPLEMENTED = "not_implemented"


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
    #: Set when there is no permitted automated route at all — the site blocks automation and
    #: the brief forbids evading it. Distinct from "not built yet": this one will not be built.
    blocked_reason: str | None = None
    note: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


_BROKEN_SCRAPER = "Browser scraper offline — targets a removed browser-use API (B14)"

CATALOGUE: tuple[SourceSpec, ...] = (
    # Tier 1 — registered browser platforms, currently non-functional.
    SourceSpec(
        "linkedin", "LinkedIn Jobs", "linkedin.com", SourceTier.TIER1, True,
        known_broken=_BROKEN_SCRAPER,
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

    SourceSpec("reed", "Reed", "reed.co.uk", SourceTier.TIER2, note="Needs a Reed API key"),
    SourceSpec("totaljobs", "Totaljobs", "totaljobs.com", SourceTier.TIER2),
    SourceSpec("cvlibrary", "CV-Library", "cv-library.co.uk", SourceTier.TIER2),
    SourceSpec("cwjobs", "CWJobs", "cwjobs.co.uk", SourceTier.TIER2),
    SourceSpec("jobsite", "Jobsite", "jobsite.co.uk", SourceTier.TIER2),
    SourceSpec("adzuna", "Adzuna", "adzuna.co.uk", SourceTier.TIER2, note="Needs an Adzuna app id"),
    SourceSpec("jobserve", "JobServe", "jobserve.com", SourceTier.TIER2),
    SourceSpec("guardianjobs", "The Guardian Jobs", "jobs.theguardian.com", SourceTier.TIER2),

    SourceSpec(
        "civilservice", "Civil Service Jobs", "civilservicejobs.service.gov.uk", SourceTier.TIER3
    ),
    SourceSpec("findajob", "Find a job — GOV.UK", "gov.uk", SourceTier.TIER3),
    SourceSpec(
        "nhsjobs", "NHS Jobs", "jobs.nhs.uk", SourceTier.TIER3,
        note="No candidate search API. NHSBSA's API is for employers publishing their own "
             "vacancies and needs eligibility approval. NHS roles are reachable via Reed/"
             "Adzuna syndication; apply on jobs.nhs.uk.",
    ),
    SourceSpec(
        "tracjobs", "TRAC (NHS recruitment)", "apps.trac.jobs", SourceTier.TIER3,
        blocked_reason=(
            "Returns HTTP 403 to every automated client and serves a 'Site unavailable' "
            "page in place of robots.txt — an explicit anti-automation control. Verified "
            "2026-08-13. Working around it would mean evading a security control, which is "
            "out of scope. Discovery must come from a syndicating source; the application "
            "itself is completed by hand on the TRAC portal."
        ),
    ),
    SourceSpec("ddat", "Digital & Data Jobs", "ddat.gov.uk", SourceTier.TIER3),

    SourceSpec("otta", "Otta / Welcome to the Jungle", "otta.com", SourceTier.TIER4),
    SourceSpec("hired", "Hired", "hired.com", SourceTier.TIER4),
    SourceSpec("builtin", "Built In", "builtin.com", SourceTier.TIER4),
    SourceSpec("technojobs", "Technojobs", "technojobs.co.uk", SourceTier.TIER4),

    SourceSpec("devsdata", "DevsData LLC", "devsdata.com", SourceTier.TIER5),
    SourceSpec("proactive", "Proactive IT Appointments", "proactive.uk.com", SourceTier.TIER5),
    SourceSpec("ashdown", "Ashdown Group", "ashdowngroup.com", SourceTier.TIER5),
    SourceSpec("datalogic", "DataLogic", "datalogic-recruitment.co.uk", SourceTier.TIER5),
)

#: Employers whose career pages are polled directly. Key format: ``careers:<slug>``.
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
    """Derive a source's current health. Never raises."""
    if spec.blocked_reason:
        return SourceHealth.UNAVAILABLE
    if not (spec.implemented or spec.key in _registered_keys()):
        return SourceHealth.NOT_IMPLEMENTED
    if spec.known_broken:
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
