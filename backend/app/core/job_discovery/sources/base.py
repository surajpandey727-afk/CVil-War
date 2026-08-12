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
from typing import Any

import httpx
import structlog

from app.core.automation.platforms.base import JobListing, JobPlatform

logger = structlog.get_logger(__name__)

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


def matches_query(query: str, *fields: str) -> bool:
    """True if every term in ``query`` appears as a whole word in the joined fields.

    Several of these boards expose no server-side search (Arbeitnow returns a fixed page), so
    filtering happens here.

    Two properties matter, both learned from wrong results:

    * **AND, not OR** — "product manager" must not match every job containing "product".
    * **Whole words, not substrings** — a plain ``in`` test made the query "ai" match
      "M*ai*ntenance Technician" and "Gr*a*ph*i*c Designer" via its tags. Short, common
      acronyms are exactly the queries this system cares about (AI, ML, BA, PM), so
      substring matching is unusable here.
    """
    terms = [t for t in re.split(r"\W+", query.lower()) if t]
    if not terms:
        return True
    haystack = " ".join(f or "" for f in fields).lower()
    words = set(re.split(r"\W+", haystack))
    return all(term in words for term in terms)


def matches_location(location: str, candidate_location: str, *, remote: bool) -> bool:
    """True if a listing plausibly satisfies the requested location.

    Remote roles match any location by construction — that is the point of remote. Otherwise
    this is a containment check in both directions so "London" matches "London, UK" and
    "Greater London" matches "London".
    """
    wanted = location.strip().lower()
    if not wanted or wanted in {"remote", "anywhere", "worldwide"}:
        return True
    if remote:
        return True
    found = (candidate_location or "").lower()
    if not found:
        return False
    if any(token in found for token in ("worldwide", "anywhere", "global")):
        return True
    return wanted in found or found in wanted


class ApiJobSource(JobPlatform):
    """A keyless, read-only job board reachable over HTTP JSON.

    Subclasses implement :meth:`_fetch` (one HTTP call returning raw records) and
    :meth:`_to_listing` (one record to a normalised :class:`JobListing`). Everything else —
    error containment, filtering, capping — is handled here so each adapter stays small.
    """

    #: Public identifier, also the ``platform`` value stored on every Job row.
    source_name: str = "api"

    @property
    def name(self) -> str:
        return self.source_name

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
