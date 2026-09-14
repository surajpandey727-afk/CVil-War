"""Keyless UK visa-sponsorship-focused job boards, scraped from server-rendered HTML.

Two sites confirmed (by live reconnaissance, not assumption) to serve full, real job data
without a login and without JS rendering:

===========  ====================================  ==========================================
Source       Coverage                              Notes
===========  ====================================  ==========================================
MoveJobs     General UK board, visa-sponsorship     Real per-job URLs exist but are wrapped in
             framing, server-side keyword search    an HTML *comment* around the card's anchor
             (``?keyword=``)                        tag — see :func:`_movejobs_url`.
Tarve        UK board explicitly cross-checked      No keyword search endpoint found; filtered
             against the Home Office Skilled        client-side (``server_side_search=False``).
             Worker sponsor register by the site    Paginated (``?page=``).
             itself
===========  ====================================  ==========================================

Three other candidates were investigated and are deliberately NOT adapters here:

* **ukvisajobs.com** — the public homepage's "Featured Jobs" have no real per-job URL (every
  link is a placeholder ``href="/"``, routed client-side); the actual catalogue with working
  URLs lives behind login on ``my.ukvisajobs.com``. Needs the assisted-login ("Connect") flow,
  not a keyless scraper.
* **civilservicejobs.service.gov.uk** — every page, including the base domain, serves a
  "Quick check needed" bot-verification gate before any content. ``robots.txt`` allows
  crawling, but the gate itself must not be automated through (see ``core.automation`` — no
  code path here solves a bot challenge). Needs the same one-time human-supervised session.
* **workinstartups.com** — confirmed (its own footer says so) to be part of the Adzuna
  network, and protected by Cloudflare against direct HTTP scraping. Its listings are already
  reachable through the existing :class:`~app.core.job_discovery.sources.uk_boards.AdzunaSource`
  once an Adzuna API key is configured — building a second, Cloudflare-fighting scraper for
  data the system can already fetch properly would be redundant and fragile.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.core.automation.platforms.base import JobListing
from app.core.job_discovery.sources.base import ApiJobSource

_HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml"}

# -- MoveJobs -------------------------------------------------------------------------------

#: The real job-detail URL is present in the server-rendered HTML but wrapped in a comment
#: (``<!--<a href="...">-->``) around the card's icon/title anchors — confirmed by direct
#: inspection, present on both the unfiltered and keyword-filtered listing pages. A DOM parser
#: correctly ignores commented-out tags, so the URL is recovered with a regex over the card's
#: raw (uncommented) HTML instead.
_MOVEJOBS_URL_RE = re.compile(r'<!--\s*<a href="(https://movejobs\.uk/jobs/[^"]+)"')

def _movejobs_url(card_html: str) -> str:
    match = _MOVEJOBS_URL_RE.search(card_html)
    return match.group(1) if match else ""


def _collapse_ws(text: str) -> str:
    return " ".join(text.split())


class MoveJobsSource(ApiJobSource):
    """https://movejobs.uk — general UK board with a visa-sponsorship framing.

    No official API; ``?keyword=`` is a real server-side GET search confirmed live (e.g.
    "data scientist" correctly returns AI Applied Engineer / Data Engineer / Data Scientist /
    Engineering Manager — Data & AI postings, not noise).
    """

    source_name = "movejobs"
    server_side_search = True
    _ENDPOINT = "https://movejobs.uk/jobs"

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if query.strip():
            params["keyword"] = query.strip()
        response = await client.get(self._ENDPOINT, params=params, headers=_HTML_HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        records: list[dict[str, Any]] = []
        for card in soup.select(".card"):
            title_div = card.select_one(".post-main-title")
            if title_div is None:
                continue
            title_node = title_div.find(string=True, recursive=False)
            title = _collapse_ws(str(title_node)) if title_node else ""
            if not title:
                continue

            badge = title_div.select_one(".badge")
            job_type = badge.get_text(strip=True) if badge else ""

            list_items = [
                _collapse_ws(li.get_text(" ", strip=True))
                for li in card.select(".rt-list > li")
            ]
            location_text = list_items[0] if len(list_items) > 0 else ""
            salary_text = list_items[1] if len(list_items) > 1 else ""
            # A third list item's "Expired" badge was investigated and rejected as a filter
            # signal: confirmed live, the server-rendered HTML shows it on literally every
            # card — including ones whose own description reads as a current, live posting.
            # It appears to be a countdown widget that defaults to "Expired" before client-
            # side JS corrects it, not a real status. Filtering on it discarded 100% of
            # results, including genuinely live ones, so it is deliberately not used here.

            description_el = card.select_one(".jddv")
            description = (
                _collapse_ws(description_el.get_text(" ", strip=True))
                if description_el
                else ""
            )

            records.append({
                "title": title,
                "job_type": job_type,
                "location": location_text,
                # The salary line is one of the search form's own bucket labels (e.g.
                # "10K - 100K GBP" for a role that pays far less), not a per-job figure —
                # see _to_listing for why this is deliberately not parsed into a number.
                "salary_text": salary_text,
                "description": description,
                "url": _movejobs_url(str(card)),
            })
            if len(records) >= limit:
                break
        return records

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        if not record["url"]:
            return None
        return JobListing(
            platform=self.source_name,
            # No stable numeric id is exposed anywhere on the listing page; the URL slug
            # (title + a short random code) is the only stable identifier available.
            platform_job_id=record["url"].rsplit("/", 1)[-1],
            title=record["title"],
            # Genuine site limitation, confirmed on both the listing card and the job's own
            # detail page: every posting shows the employer as this same generic aggregator
            # label, whoever actually posted it. Using it (rather than inventing a guess from
            # the description) keeps this honest; ApiJobSource.search() drops any listing
            # with an empty company outright, so "" here would silently discard every result
            # from this source. The real employer, when the posting names one, is usually
            # still visible in the preserved description text below.
            company="Movejob Portal",
            location=record["location"],
            url=record["url"],
            description=record["description"],
            job_type=record["job_type"],
            remote="remote" in record["location"].casefold(),
            # Deliberately not populated — see the "salary_text" comment in _fetch(). A wide,
            # nonsensical bucket like "10K - 100K GBP" would corrupt the salary-floor filter
            # (services.job_search._passes_hard_criteria) far worse than reporting no band.
            salary_min=None,
            salary_max=None,
        )


# -- Tarve ----------------------------------------------------------------------------------


class TarveSource(ApiJobSource):
    """https://tarve.co.uk — UK jobs the site itself cross-checks against the Home Office
    Skilled Worker sponsor register (independently of this system's own check in
    ``core.sponsorship``; the two are complementary, not the same data).

    No keyword search endpoint was found on the listing page, only ``?page=`` and ``?city=``
    — relevance filtering happens client-side via the base class's ``_post_filter``.
    """

    source_name = "tarve"
    server_side_search = False
    _ENDPOINT = "https://tarve.co.uk/jobs"
    #: Pages fetched per search. Bounded — the live count was ~16,900 jobs, and pulling more
    #: than a few pages of "newest" per query would be needless load for a search that only
    #: needs the most recent, relevant handful.
    _MAX_PAGES = 3

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for page in range(1, self._MAX_PAGES + 1):
            response = await client.get(
                self._ENDPOINT, params={"page": page}, headers=_HTML_HEADERS
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.select('a[href^="/jobs/"]')
            if not links:
                break  # ran past the last page
            for a in links:
                title = a.get_text(strip=True)
                href = a.get("href") or ""
                if not title or not href:
                    continue
                meta_el = a.parent.select_one(".muted") if a.parent else None
                company, location_text, posted = "", "", ""
                if meta_el:
                    parts = [p.strip() for p in meta_el.get_text().split("·")]
                    company = parts[0] if len(parts) > 0 else ""
                    location_text = parts[1] if len(parts) > 1 else ""
                    posted = parts[2] if len(parts) > 2 else ""
                records.append({
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "posted_at": posted,
                    "url": f"https://tarve.co.uk{href}" if href.startswith("/") else href,
                })
                if len(records) >= limit:
                    return records
        return records

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        if not record["company"]:
            return None
        return JobListing(
            platform=self.source_name,
            platform_job_id=record["url"].rsplit("-", 1)[-1] or record["url"],
            title=record["title"],
            company=record["company"],
            location=record["location"],
            url=record["url"],
            # The listing page is title/company/location/date only — full text lives on the
            # job's own page and is fetched on demand via the existing enrichment endpoint
            # (services.enrichment), the same pattern already used for LinkedIn cards.
            description="",
            remote="remote" in record["location"].casefold(),
            posted_at=record["posted_at"],
            raw_data={
                # Tarve's own claim, distinct from (and a corroborating second opinion to)
                # this system's independent core.sponsorship register check.
                "site_claims_verified_sponsor": True,
            },
        )


UK_VISA_SOURCES: list[type[ApiJobSource]] = [MoveJobsSource, TarveSource]
