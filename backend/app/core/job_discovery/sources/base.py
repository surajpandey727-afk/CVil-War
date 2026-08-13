"""Base class for API-backed job sources.

These are the counterpart to the browser-scraped platforms in
``app.core.automation.platforms``: same :class:`JobPlatform` contract, so they drop into the
existing ``platform_registry`` and ``services.job_search`` without either needing to change —
but they fetch over HTTP from a public JSON API instead of driving a browser.

Why this exists: the LinkedIn/Indeed/Glassdoor plugins are non-functional (they target a
browser-use API that no longer exists — see docs/PHASE0_AUDIT.md §4.3.1), scraping those sites
breaks their terms, and every keyed aggregator (Adzuna, Reed) needs the operator to register
first. These sources need no key, so discovery works out of the box.

``login``/``apply`` are deliberately unsupported. Applications happen on the source site — the
system's job is to find the role, tailor the documents, and hand over a link. That keeps the
whole discovery path clear of credential handling and terms-of-service risk.

**Attribution:** several of these APIs require crediting the source and linking back to the
original posting. Every listing therefore keeps its canonical ``url``, and the UI links to it.
Do not strip that.
"""

from __future__ import annotations

import re
from abc import abstractmethod
from enum import StrEnum
from typing import Any

import httpx
import structlog

from app.core.automation.platforms.base import JobListing, JobPlatform

logger = structlog.get_logger(__name__)


class CostType(StrEnum):
    """What running this adapter costs.

    The deployment runs under a hard zero-spend constraint, so this is enforced rather than
    documented: ``ZERO_COST_MODE`` (default on) refuses to instantiate anything that is not
    :attr:`FREE`. An adapter that could bill must therefore opt in twice — by declaring
    ``OPTIONAL_PAID`` and by the operator disabling zero-cost mode.
    """

    #: No charge under any usage pattern (public endpoint, no key, or a free-forever tier).
    FREE = "free"
    #: Works only with a credential that may meter or bill. Disabled under ZERO_COST_MODE.
    OPTIONAL_PAID = "optional_paid"
    #: Catalogued for honesty, but no adapter can run it (blocked, or no permitted route).
    UNAVAILABLE = "unavailable"


class SourceUnavailableError(RuntimeError):
    """Raised when an adapter cannot run — wrong mode, missing credential, blocked upstream."""


REQUEST_TIMEOUT_S = 25.0
USER_AGENT = "CVil-War/2.0 (job search aggregator; +https://github.com/)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def strip_html(raw: str) -> str:
    """Flatten an HTML job description to readable plain text.

    Descriptions arrive as HTML from every one of these boards. They are fed to the ATS
    keyword analyser and, eventually, an LLM prompt — markup would pollute both the keyword
    counts and the token budget.
    """
    if not raw:
        return ""
    text = raw.replace("</p>", "\n").replace("<br>", "\n").replace("<br/>", "\n")
    text = _TAG_RE.sub(" ", text)
    for entity, char in (
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
        ("&#039;", "'"), ("&apos;", "'"), ("&nbsp;", " "),
    ):
        text = text.replace(entity, char)
    text = _WS_RE.sub(" ", text)
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


#: Words that carry no discriminating signal in a job title. Requiring them would reject
#: obvious matches ("Senior Product Manager" for the query "AI Product Manager").
_STOPWORDS = frozenset(
    {"a", "an", "and", "the", "of", "for", "to", "in", "at", "or", "with", "senior", "junior",
     "staff", "principal", "lead", "head", "chief", "assistant", "associate", "i", "ii", "iii"}
)

#: Minimum share of meaningful query terms a title must carry.
#:
#: 0.6 rather than 0.5, chosen against real results:
#:   * 3-term "AI Product Manager" needs 2 -> "Senior Product Manager" (0.67) is kept, which
#:     0.5 also did.
#:   * 2-term "Product Manager" needs both -> "Compliance Advisory Manager" (0.5) is now
#:     rejected, where 0.5 let every job with "Manager" anywhere in the title through.
_MATCH_THRESHOLD = 0.6


def relevance(query: str, title: str, tags: str = "") -> float:
    """Score 0-1 for how well a listing title answers a query.

    Replaces an all-terms-must-match test that was badly wrong in practice: searching
    "AI Product Manager" returned nothing, because almost no title contains all three of
    "ai", "product" and "manager" — "Senior Product Manager" was rejected for lacking "ai".
    A job search that discards the single most obvious match is worse than useless.

    Scoring:

    * Terms are matched as **whole words**, never substrings. A plain ``in`` test made the
      query "ai" match "M*ai*ntenance Technician"; short acronyms (AI, ML, BA, PM) are exactly
      what this product searches for, so substring matching is unusable.
    * The **title** carries the signal; tags are a weaker secondary. Descriptions are excluded
      entirely — a long description mentions almost every common word somewhere, which is how
      "product manager" once returned an "Inside Sales Contractor".
    * Filler words ("senior", "the") are dropped so they neither help nor hurt.
    """
    terms = [t for t in re.split(r"\W+", query.lower()) if t and t not in _STOPWORDS]
    if not terms:
        return 1.0
    title_words = set(re.split(r"\W+", (title or "").lower()))
    tag_words = set(re.split(r"\W+", (tags or "").lower()))

    hits = 0.0
    for term in terms:
        if term in title_words:
            hits += 1.0
        elif term in tag_words:
            hits += 0.5  # a tag is corroborating evidence, not the role name
    return min(hits / len(terms), 1.0)


def matches_query(query: str, *fields: str) -> bool:
    """True if a listing is relevant enough to show. See :func:`relevance` for the scoring."""
    if not query.strip():
        return True
    title = fields[0] if fields else ""
    tags = " ".join(fields[1:]) if len(fields) > 1 else ""
    return relevance(query, title, tags) >= _MATCH_THRESHOLD


#: Regions that contain each other for job-search purposes. Typing "London, UK" should not
#: discard a UK-wide or Europe-remote role — those are all commutable or workable, and
#: excluding them is what made a London search return almost nothing.
_REGION_ALIASES: dict[str, frozenset[str]] = {
    "london": frozenset({"london", "uk", "united kingdom", "gb", "england", "britain",
                         "europe", "emea", "greater london"}),
    "uk": frozenset({"uk", "united kingdom", "gb", "england", "scotland", "wales", "london",
                     "britain", "europe", "emea"}),
    "united kingdom": frozenset({"uk", "united kingdom", "gb", "england", "london", "europe",
                                 "emea"}),
    "europe": frozenset({"europe", "emea", "uk", "united kingdom", "london", "germany",
                         "netherlands", "france", "spain", "ireland", "poland"}),
}

#: A listing whose location says one of these is open to anyone.
_ANYWHERE = ("worldwide", "anywhere", "global", "remote", "multiple", "various")


def matches_location(location: str, candidate_location: str, *, remote: bool) -> bool:
    """True if a listing plausibly satisfies the requested location.

    Deliberately generous, because a false negative silently hides a real job while a false
    positive is one row the operator can ignore. Three rules:

    * A **remote** role matches any request — that is what remote means.
    * A listing with **no stated location**, or one saying "worldwide"/"anywhere", matches.
      Several sources (Arbeitnow, some ATS boards) simply omit the field, and excluding them
      dropped whole sources from every located search.
    * Otherwise the request and the listing must **share a region token**, using the alias
      table so "London, UK" matches "London", "United Kingdom" and "Europe".
    """
    wanted_raw = location.strip().lower()
    if not wanted_raw or any(a in wanted_raw for a in _ANYWHERE):
        return True
    if remote:
        return True

    found = (candidate_location or "").strip().lower()
    if not found:
        return True  # unknown, not "elsewhere" — see the docstring
    if any(a in found for a in _ANYWHERE):
        return True

    # Expand "london, uk" -> {london, uk} plus every alias of each part.
    wanted_tokens: set[str] = set()
    for part in re.split(r"[,/|]| and ", wanted_raw):
        part = part.strip()
        if not part:
            continue
        wanted_tokens.add(part)
        wanted_tokens |= _REGION_ALIASES.get(part, frozenset())

    return any(token and token in found for token in wanted_tokens)


class ApiJobSource(JobPlatform):
    """A keyless, read-only job board reachable over HTTP JSON.

    Subclasses implement :meth:`_fetch` (one HTTP call returning raw records) and
    :meth:`_to_listing` (one record to a normalised :class:`JobListing`). Everything else —
    error containment, filtering, capping — is handled here so each adapter stays small.
    """

    #: Public identifier, also the ``platform`` value stored on every Job row.
    source_name: str = "api"

    #: What this adapter costs to run. Enforced by ``ZERO_COST_MODE`` — see :class:`CostType`.
    cost_type: CostType = CostType.FREE
    #: Estimated per-run spend in the account currency. Must stay 0 for a FREE adapter.
    estimated_cost: float = 0.0
    #: Settings attribute holding this adapter's credential, when it needs one.
    api_key_field: str | None = None

    def __init__(self) -> None:
        """Refuse to construct a billable adapter while zero-cost mode is on.

        Enforced at construction, not at call time, so a paid source cannot be reached by any
        route — a scheduled refresh, a retry, or a hand-built request all fail the same way.
        The brief's requirement is that the system can *never* unexpectedly generate a bill;
        a check on the search path alone would leave the other entry points open.
        """
        from app.config.settings import get_settings

        if get_settings().zero_cost_mode and self.cost_type is not CostType.FREE:
            raise SourceUnavailableError(
                f"{self.source_name}: cost_type={self.cost_type.value} is disabled while "
                "ZERO_COST_MODE is on. Set ZERO_COST_MODE=false to allow billable sources."
            )

    @property
    def name(self) -> str:
        return self.source_name

    # -- Capability + health contract --------------------------------------------------

    def capabilities(self) -> dict[str, bool]:
        """What this adapter can do. Callers branch on this rather than on the class.

        Defaults describe a read-only discovery source: it can search and hand back an
        application URL, but cannot submit on the user's behalf.
        """
        return {
            "search": True,
            "get_job": False,
            "application_url": True,
            "can_apply": False,
            "needs_credential": self.api_key_field is not None,
        }

    def get_application_url(self, listing: JobListing) -> str:
        """Where a human completes this application. Defaults to the posting itself."""
        return listing.url

    async def health_check(self) -> tuple[str, str]:
        """Probe the upstream endpoint. Returns ``(state, detail)``; never raises.

        States match ``source_registry.SourceHealth``. This is a *live* probe, distinct from
        the registry's static derivation — the registry knows an adapter exists, this knows
        whether it answered just now.
        """
        from app.config.settings import get_settings

        if get_settings().zero_cost_mode and self.cost_type is not CostType.FREE:
            return "unavailable", "disabled by ZERO_COST_MODE"
        try:
            listings = await self.search(query="", location="", filters={"limit": 1})
        except SourceUnavailableError as exc:
            return "unavailable", str(exc)
        except Exception as exc:  # health must never propagate
            return "degraded", str(exc)[:160]
        return ("live", f"{len(listings)} returned") if listings else ("degraded", "no results")

    # -- JobPlatform surface that does not apply to a read-only API ------------------

    async def login(self, credentials: dict[str, str]) -> bool:
        """No-op: these APIs are public and take no credentials."""
        return True

    async def scrape_details(self, job_url: str) -> JobListing | None:
        """Not supported — ``search`` already returns the full description."""
        return None

    async def apply(
        self,
        job: JobListing,
        resume_path: str,
        cover_letter_path: str | None = None,
    ) -> bool:
        """Not supported. Applications are completed on the source site by the user."""
        raise NotImplementedError(
            f"{self.source_name} is a discovery-only source; apply on the posting itself."
        )

    # -- Subclass contract ------------------------------------------------------------

    @abstractmethod
    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        """Return raw job records from the upstream API."""

    @abstractmethod
    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        """Normalise one raw record, or None to skip it."""

    def _post_filter(self, listing: JobListing, query: str, location: str) -> bool:
        """Relevance + location filter applied after normalisation.

        The query is matched against **title and tags only, never the description**. Matching
        the description looked reasonable and was badly wrong in practice: searching "product
        manager" returned an "Inside Sales Contractor" and a "Merchandising Execution
        Associate", because long job descriptions mention both "product" and "manager"
        somewhere. Title+tags is the signal; the description is noise.
        """
        return matches_query(
            query, listing.title, " ".join(listing.skills_required)
        ) and matches_location(location, listing.location, remote=listing.remote)

    # -- Public entry point -----------------------------------------------------------

    async def search(
        self,
        query: str,
        location: str = "",
        filters: dict[str, Any] | None = None,
    ) -> list[JobListing]:
        """Fetch and normalise listings. Never raises — a dead source yields no results.

        Containment matters here: ``services.job_search`` fans out across every registered
        source, and one board being down or changing its schema must not take the whole
        search with it.
        """
        limit = int((filters or {}).get("limit") or 50)
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_S,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            ) as client:
                records = await self._fetch(client, query, location, limit)
        except httpx.HTTPStatusError as exc:
            # 429/403 are throttling or a block, not a bug. Distinguished from a generic
            # failure so the operator can tell "we hit the free ceiling" from "this broke",
            # and so one throttled source never ends a multi-source run.
            status = exc.response.status_code
            state = "rate_limited" if status in (429, 503) else "degraded"
            logger.warning(
                "job_source.http_error",
                source=self.source_name,
                status=status,
                state=state,
                query=query,
            )
            return []
        except Exception as exc:
            logger.warning(
                "job_source.fetch_failed",
                source=self.source_name,
                error=str(exc)[:200],
                query=query,
            )
            return []

        listings: list[JobListing] = []
        for record in records:
            try:
                listing = self._to_listing(record)
            except Exception as exc:
                # One malformed record must not lose the rest of the page.
                logger.debug(
                    "job_source.record_skipped", source=self.source_name, error=str(exc)[:120]
                )
                continue
            if listing is None or not listing.title or not listing.company:
                continue
            if not self._post_filter(listing, query, location):
                continue
            listings.append(listing)
            if len(listings) >= limit:
                break

        logger.info(
            "job_source.search_complete",
            source=self.source_name,
            query=query,
            location=location,
            fetched=len(records),
            kept=len(listings),
        )
        return listings
