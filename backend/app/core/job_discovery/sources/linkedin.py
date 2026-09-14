"""LinkedIn job discovery.

Reads the job search LinkedIn serves to signed-out visitors. That choice is deliberate and
worth stating, because the obvious alternative is worse: the operator has now connected a
LinkedIn session, and it would have been easy to drive discovery through it. Doing so would
put their personal account behind every one of the hundreds of requests a discovery sweep
makes, which is exactly the activity LinkedIn restricts accounts for. The public listing
carries the same jobs and risks nothing, so the session is reserved for applying — the one
thing that genuinely cannot be done without it.

Two upstream behaviours shape the implementation, both observed rather than assumed:

* **Pagination is real but capped.** Each page returns ten cards and ``start`` walks them.
* **The location filter is loose.** A search for "London, United Kingdom" returned a Milton
  Keynes role. ``server_side_location`` is therefore False so the strict post-filter runs —
  trusting LinkedIn's geography here would reintroduce the London bug on a new source.

Requests are paced. The detail endpoint returned 429 under a burst during development, and a
rate limit is a request to slow down, not an obstacle to route around.
"""
# Curly quotes and bullets appear deliberately: they are what real postings use,
# and substituting ASCII look-alikes would stop exercising the case under test.

from __future__ import annotations

import asyncio
import re
from html import unescape
from typing import Any

import httpx
import structlog

from app.core.automation.platforms.base import JobListing
from app.core.job_discovery.location import location_matches
from app.core.job_discovery.sources.base import (
    USER_AGENT,
    ApiJobSource,
    SourceUnavailableError,
    strip_html,
)

logger = structlog.get_logger(__name__)

_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

#: Cards per page, fixed by the endpoint.
_PAGE_SIZE = 10
#: Ceiling on pages per search. Ten pages is a hundred roles, more than enough for one sweep
#: and few enough to stay unremarkable.
_MAX_PAGES = 10
#: Gap between search pages. Slower than a person clicking "next", deliberately.
_PAGE_DELAY = 2.0
#: Gap between description fetches. 6s was comfortable in testing where a burst was not.
_DETAIL_DELAY = 6.0
#: How many descriptions to pull per sweep. The rest arrive when a job is opened.
_MAX_DETAILS = 12

_ENTITY = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"')
_CARD = re.compile(r"<li>(.*?)</li>", re.S)
_TITLE = re.compile(r'base-search-card__title[^>]*>\s*(.*?)\s*<', re.S)
_COMPANY = re.compile(r'base-search-card__subtitle.*?<a[^>]*>\s*(.*?)\s*</a>', re.S)
_LOCATION = re.compile(r'job-search-card__location[^>]*>\s*(.*?)\s*<', re.S)
_POSTED = re.compile(r'datetime="([\d-]+)"')
_SALARY = re.compile(r'job-search-card__salary-info[^>]*>\s*(.*?)\s*</div>', re.S)
# The body lives in the markup div, not the wrapper: matching on ``description__text``
# alone stopped at the class attribute itself and yielded 25 characters of markup.
_DESCRIPTION = re.compile(
    r'show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', re.S
)
#: Seniority level / Employment type / Job function / Industries, as LinkedIn labels them.
_CRITERION = re.compile(
    r'job-criteria-subheader">\s*(.*?)\s*</h3>\s*'
    r'<span[^>]*job-criteria-text[^>]*>\s*(.*?)\s*</span>',
    re.S,
)
_LINK = re.compile(r'base-card__full-link"[^>]*href="([^"?]+)')


#: Block-level tags that end a line, and list items that begin a bullet. Converting these
#: before stripping the rest is what keeps a bulleted requirements section from arriving as
#: one continuous run of prose.
_LINE_BREAK = re.compile(r"</?(?:br|p|div|tr|h[1-6])\b[^>]*>", re.I)
_LIST_ITEM = re.compile(r"<li\b[^>]*>", re.I)


def _clean(raw: str) -> str:
    """Collapse a fragment of LinkedIn's markup into readable text, keeping its structure.

    Line breaks and list items survive as newlines and bullets. They matter: a posting's
    requirements are almost always a list, and a list flattened into prose cannot be read back
    out as separate requirements by anything.
    """
    text = _LIST_ITEM.sub("\n\u2022 ", raw)
    text = _LINE_BREAK.sub("\n", text)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    # Collapse runs of spaces and tabs, but never newlines — they are the structure.
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def _flat(raw: str) -> str:
    """Single-line text, for the short fields where newlines would be noise."""
    return re.sub(r"\s+", " ", _clean(raw)).strip()


def _salary_band(text: str) -> tuple[float | None, float | None, str]:
    """Parse "£60,000 - £75,000" into a band. Returns (None, None, ccy) when absent.

    A missing salary must stay missing: inventing a midpoint would feed a fabricated number
    into ranking and into the operator's expectations.
    """
    if not text:
        return None, None, "GBP"
    currency = "GBP" if "£" in text else "USD" if "$" in text else "EUR" if "€" in text else "GBP"
    numbers = [
        float(n.replace(",", "")) for n in re.findall(r"[\d,]+(?:\.\d+)?", text) if n.strip(",")
    ]
    # "£60,000/yr - £75,000/yr" yields two; a single figure is a floor, not a band.
    if len(numbers) >= 2:
        return min(numbers[:2]), max(numbers[:2]), currency
    if len(numbers) == 1:
        return numbers[0], None, currency
    return None, None, currency


class LinkedInSource(ApiJobSource):
    """LinkedIn's public job listing.

    Registered as ``linkedin`` so that jobs discovered here land on the same ``Job.platform``
    the apply path already understands, and so the source appears in the catalogue the
    Sources screen renders rather than needing a second list.
    """

    source_name = "linkedin"

    #: Keywords are applied upstream; geography is not, whatever the parameter suggests.
    server_side_search = True
    server_side_location = False

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        """Walk the paged listing, then fill in descriptions for the first few."""
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        pages = min(_MAX_PAGES, max(1, -(-limit // _PAGE_SIZE)))

        for page in range(pages):
            if page:
                await asyncio.sleep(_PAGE_DELAY)
            html = await self._page(client, query, location, page * _PAGE_SIZE)
            fresh = [r for r in self._parse_cards(html) if r["job_id"] not in seen]
            if not fresh:
                # Either the listing is exhausted or it has started repeating; both mean stop.
                break
            seen.update(r["job_id"] for r in fresh)
            records.extend(fresh)
            if len(records) >= limit:
                break

        await self._add_descriptions(client, records[:_MAX_DETAILS])
        return records[:limit]

    async def _page(
        self, client: httpx.AsyncClient, query: str, location: str, start: int
    ) -> str:
        """One page of results, translating a rate limit into the health the registry knows."""
        try:
            response = await client.get(
                _SEARCH,
                params={"keywords": query, "location": location, "start": start},
                headers={"Accept-Language": "en-GB,en;q=0.9"},
            )
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(f"LinkedIn unreachable: {exc}") from exc

        if response.status_code == 429:
            # Reported rather than retried. Backing off is the correct response to being asked
            # to slow down; hammering through it is what gets a source blocked outright.
            raise SourceUnavailableError(
                "LinkedIn rate-limited this search. It will be retried on the next sweep."
            )
        if response.status_code >= 400:
            raise SourceUnavailableError(f"LinkedIn returned HTTP {response.status_code}")
        return response.text

    def _parse_cards(self, html: str) -> list[dict[str, Any]]:
        """Extract one record per card.

        Parsed per-card rather than by running each pattern across the whole page: a card
        missing its salary would otherwise shift every later card's salary up by one, which
        silently attaches real numbers to the wrong jobs.
        """
        records: list[dict[str, Any]] = []
        for chunk in _CARD.findall(html):
            entity = _ENTITY.search(chunk)
            title = _TITLE.search(chunk)
            if not (entity and title):
                continue
            company = _COMPANY.search(chunk)
            location = _LOCATION.search(chunk)
            posted = _POSTED.search(chunk)
            salary = _SALARY.search(chunk)
            link = _LINK.search(chunk)
            records.append({
                "job_id": entity.group(1),
                "title": _flat(title.group(1)),
                "company": _flat(company.group(1)) if company else "",
                "location": _flat(location.group(1)) if location else "",
                "posted_at": posted.group(1) if posted else "",
                "salary": _flat(salary.group(1)) if salary else "",
                "url": link.group(1) if link else "",
                "description": "",
            })
        return records

    async def fetch_detail(self, job_id: str) -> dict[str, Any]:
        """The full posting for one job: body text and LinkedIn's own criteria labels.

        Exposed separately from the sweep because that is how it is actually used — a sweep
        that pulled every description would make a hundred detail requests and be rate-limited
        long before it finished, whereas a job the operator has opened is one request for
        something they are actually reading.
        """
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"},
        ) as client:
            response = await client.get(_DETAIL.format(job_id=job_id))

        if response.status_code == 429:
            raise SourceUnavailableError(
                "LinkedIn is rate-limiting detail requests. Try again in a few minutes."
            )
        if response.status_code >= 400:
            raise SourceUnavailableError(f"LinkedIn returned HTTP {response.status_code}")

        body = _DESCRIPTION.search(response.text)
        criteria = {
            _flat(label): _flat(value)
            for label, value in _CRITERION.findall(response.text)
        }
        return {
            "description": _clean(body.group(1)) if body else "",
            # Kept as LinkedIn's own labels rather than remapped: the posting says
            # "Seniority level", and inventing a different vocabulary here would make the
            # stored record disagree with the page it came from.
            "criteria": criteria,
        }

    async def _add_descriptions(
        self, client: httpx.AsyncClient, records: list[dict[str, Any]]
    ) -> None:
        """Fetch descriptions for a bounded slice, pacing between each.

        A failure here degrades one record to an empty description rather than losing the
        sweep: a job with no description is still a job worth showing.
        """
        for index, record in enumerate(records):
            if index:
                await asyncio.sleep(_DETAIL_DELAY)
            try:
                response = await client.get(_DETAIL.format(job_id=record["job_id"]))
                if response.status_code == 429:
                    logger.info("linkedin_details_rate_limited", fetched=index)
                    return
                if response.status_code >= 400:
                    continue
                body = _DESCRIPTION.search(response.text)
                if body:
                    record["description"] = _clean(body.group(1))
                    record["criteria"] = {
                        _flat(label): _flat(value)
                        for label, value in _CRITERION.findall(response.text)
                    }
            except httpx.HTTPError as exc:
                logger.debug("linkedin_detail_failed", job_id=record["job_id"], error=str(exc))

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        job_id = str(record.get("job_id") or "")
        title = (record.get("title") or "").strip()
        if not job_id or not title:
            return None

        low, high, currency = _salary_band(record.get("salary") or "")
        location = record.get("location") or ""
        return JobListing(
            platform=self.source_name,
            platform_job_id=job_id,
            title=title,
            company=(record.get("company") or "").strip(),
            location=location,
            # The canonical public permalink, not the card's tracking-laden href. Dedup
            # canonicalises URLs, but a stable one here keeps the stored record clean.
            url=record.get("url") or f"https://www.linkedin.com/jobs/view/{job_id}/",
            description=strip_html(record.get("description") or ""),
            salary_min=low,
            salary_max=high,
            salary_currency=currency,
            remote="remote" in location.lower(),
            posted_at=record.get("posted_at") or "",
            raw_data={"linkedin_job_id": job_id},
        )

    async def health_check(self) -> tuple[str, str]:
        """One page, no descriptions — enough to answer "is LinkedIn responding?".

        The inherited probe runs a full ``search``, which for this source means ten paced
        pages plus description fetches. That took longer than the verification sweep's own
        timeout, so the honest answer "it works" was being reported as "no answer within 25s".
        A health check must be cheaper than the thing it is checking.
        """
        try:
            async with httpx.AsyncClient(
                timeout=12,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"},
            ) as client:
                html = await self._page(client, "product manager", "London, United Kingdom", 0)
        except SourceUnavailableError as exc:
            return "rate_limited" if "rate-limited" in str(exc) else "unavailable", str(exc)
        except Exception as exc:  # health must never propagate
            return "degraded", str(exc)[:160]

        found = len(self._parse_cards(html))
        return ("live", f"{found} returned") if found else ("degraded", "no cards in response")

    def _post_filter(self, listing: JobListing, query: str, location: str) -> bool:
        """Apply the strict geography the base class's lenient matcher does not.

        Observed, not assumed: a search for "London, United Kingdom" returned roles in Milton
        Keynes, Cambridge and Reading, and the inherited filter kept all of them. That is the
        same defect as the original London bug, arriving on a new source — so this reuses the
        matcher written to fix it rather than inventing a second notion of "in London".
        """
        if not super()._post_filter(listing, query, location):
            return False
        if not location.strip():
            return True
        return location_matches(location, listing.location, remote=listing.remote)

    def get_application_url(self, listing: JobListing) -> str:
        """Where the operator — or the agent — goes to apply."""
        job_id = listing.raw_data.get("linkedin_job_id") or listing.platform_job_id
        return f"https://www.linkedin.com/jobs/view/{job_id}/"
