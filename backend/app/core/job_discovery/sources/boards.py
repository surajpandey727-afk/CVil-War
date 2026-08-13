"""Concrete keyless job-board adapters.

Four public JSON APIs, each requiring no registration:

===========  ====================================  ==========================================
Source       Coverage                              Notes
===========  ====================================  ==========================================
Remotive     Remote, global, curated               Server-side ``search``; salary is free text
Jobicy       Remote, filterable by region          ``geo`` narrows to uk / europe / usa
Arbeitnow    Europe (Germany-heavy), on-site+remote No server-side search — filtered locally
RemoteOK     Remote, global, tech-heavy            First array element is a legal notice
===========  ====================================  ==========================================

All four require attribution and a link back to the original posting; ``JobListing.url`` is
always the canonical source URL and the UI links to it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.automation.platforms.base import JobListing
from app.core.job_discovery.sources.base import ApiJobSource, strip_html

# Jobicy's ``geo`` vocabulary. Anything unmapped is dropped so a typo widens the search
# rather than 400-ing the request (an unknown geo is rejected by their API).
# Verified against the live API: it accepts the short code "uk" and 400s on
# "united-kingdom", so these must be the codes, not the display names.
_JOBICY_GEO = {
    "uk": "uk", "united kingdom": "uk", "gb": "uk", "britain": "uk",
    "england": "uk", "london": "uk", "scotland": "uk", "wales": "uk",
    "usa": "usa", "us": "usa", "united states": "usa",
    "canada": "canada", "europe": "europe", "emea": "emea",
    "germany": "germany", "india": "india", "australia": "australia",
}


def _iso(value: Any) -> str:
    """Best-effort ISO-8601 string from the assorted date shapes these boards emit."""
    if not value:
        return ""
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=UTC).isoformat()
    return text


class RemotiveSource(ApiJobSource):
    """https://remotive.com — curated remote roles, server-side keyword search."""

    source_name = "remotive"
    # Remotive applies `search` upstream; these are remote roles so location is moot.
    server_side_search = True
    _ENDPOINT = "https://remotive.com/api/remote-jobs"

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": min(limit * 2, 100)}
        if query.strip():
            params["search"] = query.strip()
        response = await client.get(self._ENDPOINT, params=params)
        response.raise_for_status()
        return response.json().get("jobs", []) or []

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        where = record.get("candidate_required_location") or "Remote"
        return JobListing(
            platform=self.source_name,
            platform_job_id=str(record.get("id") or ""),
            title=(record.get("title") or "").strip(),
            company=(record.get("company_name") or "").strip(),
            location=where,
            url=record.get("url") or "",
            description=strip_html(record.get("description") or ""),
            job_type=(record.get("job_type") or "").replace("_", "-"),
            remote=True,
            skills_required=[t for t in (record.get("tags") or []) if isinstance(t, str)],
            posted_at=_iso(record.get("publication_date")),
            raw_data={"salary": record.get("salary"), "category": record.get("category")},
        )


class JobicySource(ApiJobSource):
    """https://jobicy.com — remote roles with a usable regional filter."""

    source_name = "jobicy"
    _ENDPOINT = "https://jobicy.com/api/v2/remote-jobs"

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"count": min(max(limit, 1), 50)}
        geo = _JOBICY_GEO.get(location.strip().lower())
        if geo:
            params["geo"] = geo
        response = await client.get(self._ENDPOINT, params=params)
        response.raise_for_status()
        return response.json().get("jobs", []) or []

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        job_type = record.get("jobType")
        if isinstance(job_type, list):
            job_type = job_type[0] if job_type else ""
        return JobListing(
            platform=self.source_name,
            platform_job_id=str(record.get("id") or ""),
            title=(record.get("jobTitle") or "").strip(),
            company=(record.get("companyName") or "").strip(),
            location=record.get("jobGeo") or "Remote",
            url=record.get("url") or "",
            description=strip_html(
                record.get("jobDescription") or record.get("jobExcerpt") or ""
            ),
            job_type=str(job_type or ""),
            remote=True,
            posted_at=_iso(record.get("pubDate")),
            raw_data={
                "level": record.get("jobLevel"), "industry": record.get("jobIndustry")
            },
        )


class ArbeitnowSource(ApiJobSource):
    """https://www.arbeitnow.com — European roles including on-site, no search parameter."""

    source_name = "arbeitnow"
    _ENDPOINT = "https://www.arbeitnow.com/api/job-board-api"

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        response = await client.get(self._ENDPOINT)
        response.raise_for_status()
        return response.json().get("data", []) or []

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        job_types = record.get("job_types") or []
        return JobListing(
            platform=self.source_name,
            platform_job_id=str(record.get("slug") or ""),
            title=(record.get("title") or "").strip(),
            company=(record.get("company_name") or "").strip(),
            location=record.get("location") or "",
            url=record.get("url") or "",
            description=strip_html(record.get("description") or ""),
            job_type=str(job_types[0]) if job_types else "",
            remote=bool(record.get("remote")),
            skills_required=[t for t in (record.get("tags") or []) if isinstance(t, str)],
            posted_at=_iso(record.get("created_at")),
            raw_data={"visa_sponsorship": record.get("visa_sponsorship")},
        )


class RemoteOkSource(ApiJobSource):
    """https://remoteok.com — global remote, tech-heavy.

    Their API's first array element is a legal/attribution notice rather than a job; it is
    identified by the absence of a ``position`` field and skipped.
    """

    source_name = "remoteok"
    _ENDPOINT = "https://remoteok.com/api"

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        response = await client.get(self._ENDPOINT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return []
        return [r for r in payload if isinstance(r, dict) and r.get("position")]

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        salary_min = record.get("salary_min") or None
        salary_max = record.get("salary_max") or None
        return JobListing(
            platform=self.source_name,
            platform_job_id=str(record.get("id") or record.get("slug") or ""),
            title=(record.get("position") or "").strip(),
            company=(record.get("company") or "").strip(),
            location=record.get("location") or "Remote",
            url=record.get("url") or "",
            description=strip_html(record.get("description") or ""),
            remote=True,
            salary_min=float(salary_min) if salary_min else None,
            salary_max=float(salary_max) if salary_max else None,
            skills_required=[t for t in (record.get("tags") or []) if isinstance(t, str)],
            posted_at=_iso(record.get("date")),
            raw_data={"source": "remoteok"},
        )


ALL_SOURCES: list[type[ApiJobSource]] = [
    RemotiveSource,
    JobicySource,
    ArbeitnowSource,
    RemoteOkSource,
]
