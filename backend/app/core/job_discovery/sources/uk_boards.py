"""UK aggregator adapters — Adzuna and Reed.

These are the depth the keyless remote boards cannot provide. Measured on the live APIs while
writing this, "product manager" within 30 miles of London returned **5,587** results from
Adzuna and **2,213** from Reed, against roughly 25 from all four keyless boards combined.

Both need a key, and both have a free tier with no card on file, so neither can bill by
surprise — they are :attr:`CostType.FREE` adapters that simply need credentials. Without a key
the source reports ``auth_required`` and the run continues on every other source.

**Radius units differ and the difference is silent.** Reed's ``distanceFromLocation`` is in
miles; Adzuna's ``distance`` is in kilometres. Passing 30 to both would quietly give Reed a
30-mile radius and Adzuna an 18.6-mile one — the same query returning different geography per
source, with nothing in either response indicating it. :func:`miles_to_km` makes the
conversion explicit at the one place it matters.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config.settings import get_settings
from app.core.automation.platforms.base import JobListing
from app.core.job_discovery.sources.base import ApiJobSource, CostType, strip_html

#: The search radius the product offers, in miles. Both adapters convert from this single
#: number so the two sources always cover the same ground.
DEFAULT_RADIUS_MILES = 30
MAX_RADIUS_MILES = 30

_KM_PER_MILE = 1.609344


def miles_to_km(miles: float) -> int:
    """Convert a mile radius to whole kilometres, rounding up.

    Rounding up rather than to nearest: a slightly wider search returns a few extra rows the
    operator can ignore, whereas rounding down silently drops jobs at the edge of the radius
    they asked for.
    """
    return int(miles * _KM_PER_MILE + 0.999)


def _radius_miles(filters: dict[str, Any] | None) -> int:
    raw = (filters or {}).get("radius_miles") or DEFAULT_RADIUS_MILES
    try:
        return max(1, min(int(raw), MAX_RADIUS_MILES))
    except (TypeError, ValueError):
        return DEFAULT_RADIUS_MILES


class AdzunaSource(ApiJobSource):
    """https://developer.adzuna.com — UK-wide aggregator, free tier ~1,000 calls/month.

    The quota is the binding constraint, not the cost: one call returns up to 50 results, so
    a broad sweep across many role titles burns it quickly. Callers should prefer fewer, wider
    queries over many narrow ones.
    """

    source_name = "adzuna"
    cost_type = CostType.FREE
    api_key_field = "adzuna_app_id"
    # Both parameters are applied by the API itself, so the local filters must stand
    # down — re-checking them discards results the server deliberately matched.
    server_side_search = True
    server_side_location = True
    _ENDPOINT = "https://api.adzuna.com/v1/api/jobs/gb/search/1"

    def capabilities(self) -> dict[str, bool]:
        caps = super().capabilities()
        caps["needs_credential"] = True
        return caps

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        settings = get_settings()
        app_id = settings.adzuna_app_id.get_secret_value()
        app_key = settings.adzuna_app_key.get_secret_value()
        if not (app_id and app_key):
            # Not an error: an unconfigured source reports auth_required and the multi-source
            # run continues. Raising here would take the whole search down with it.
            return []

        params: dict[str, Any] = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": min(max(limit, 1), 50),
            "content-type": "application/json",
        }
        if query.strip():
            params["what"] = query.strip()
        if location.strip():
            params["where"] = location.strip()
            # Adzuna measures in kilometres — see the module docstring.
            params["distance"] = miles_to_km(self._radius)
        response = await client.get(self._ENDPOINT, params=params)
        response.raise_for_status()
        return response.json().get("results", []) or []

    async def search(
        self, query: str, location: str = "", filters: dict[str, Any] | None = None
    ) -> list[JobListing]:
        self._radius = _radius_miles(filters)
        return await super().search(query, location, filters)

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        company = record.get("company") or {}
        where = record.get("location") or {}
        salary_min = record.get("salary_min")
        salary_max = record.get("salary_max")
        return JobListing(
            platform=self.source_name,
            platform_job_id=str(record.get("id") or ""),
            title=(record.get("title") or "").strip(),
            company=(
                (company.get("display_name") or "").strip()
                if isinstance(company, dict)
                else ""
            ),
            location=(where.get("display_name") or "") if isinstance(where, dict) else "",
            url=record.get("redirect_url") or "",
            description=strip_html(record.get("description") or ""),
            job_type=str(record.get("contract_time") or ""),
            salary_min=float(salary_min) if salary_min else None,
            salary_max=float(salary_max) if salary_max else None,
            salary_currency="GBP",
            posted_at=str(record.get("created") or ""),
            raw_data={
                # Adzuna infers a salary when the advert omits one. Recording the flag keeps
                # a guess from being presented to the user as a published band.
                "salary_is_predicted": record.get("salary_is_predicted"),
                "category": (record.get("category") or {}).get("label"),
            },
        )


class ReedSource(ApiJobSource):
    """https://www.reed.co.uk/developers — UK jobs, radius natively in miles.

    Authenticates with HTTP Basic using the API key as the username and an empty password,
    which is Reed's documented scheme.
    """

    source_name = "reed"
    cost_type = CostType.FREE
    api_key_field = "reed_api_key"
    # Both parameters are applied by the API itself, so the local filters must stand
    # down — re-checking them discards results the server deliberately matched.
    server_side_search = True
    server_side_location = True
    _ENDPOINT = "https://www.reed.co.uk/api/1.0/search"

    def capabilities(self) -> dict[str, bool]:
        caps = super().capabilities()
        caps["needs_credential"] = True
        return caps

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        key = get_settings().reed_api_key.get_secret_value()
        if not key:
            return []

        params: dict[str, Any] = {"resultsToTake": min(max(limit, 1), 100)}
        if query.strip():
            params["keywords"] = query.strip()
        if location.strip():
            params["locationName"] = location.strip()
            # Already miles — no conversion, unlike Adzuna.
            params["distanceFromLocation"] = self._radius
        for key_name, filter_name in (
            ("permanent", "permanent"),
            ("fullTime", "full_time"),
            ("minimumSalary", "min_salary"),
        ):
            value = (self._filters or {}).get(filter_name)
            if value is not None:
                params[key_name] = value

        token = base64.b64encode(f"{key}:".encode()).decode()
        response = await client.get(
            self._ENDPOINT, params=params, headers={"Authorization": f"Basic {token}"}
        )
        response.raise_for_status()
        return response.json().get("results", []) or []

    async def search(
        self, query: str, location: str = "", filters: dict[str, Any] | None = None
    ) -> list[JobListing]:
        self._radius = _radius_miles(filters)
        self._filters = filters or {}
        return await super().search(query, location, filters)

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        job_id = str(record.get("jobId") or "")
        salary_min = record.get("minimumSalary")
        salary_max = record.get("maximumSalary")
        return JobListing(
            platform=self.source_name,
            platform_job_id=job_id,
            title=(record.get("jobTitle") or "").strip(),
            company=(record.get("employerName") or "").strip(),
            location=record.get("locationName") or "",
            url=record.get("jobUrl") or f"https://www.reed.co.uk/jobs/{job_id}",
            description=strip_html(record.get("jobDescription") or ""),
            salary_min=float(salary_min) if salary_min else None,
            salary_max=float(salary_max) if salary_max else None,
            salary_currency=record.get("currency") or "GBP",
            # Reed dates are dd/MM/yyyy; kept verbatim rather than guessed at, since a
            # mis-parsed date silently distorts every "posted within" filter.
            posted_at=str(record.get("date") or ""),
            raw_data={
                "employer_id": record.get("employerId"),
                "applications": record.get("applications"),
                "expiration_date": record.get("expirationDate"),
            },
        )

    def get_application_url(self, listing: JobListing) -> str:
        """Reed hosts the application itself unless the employer redirects externally."""
        return listing.url


UK_SOURCES: list[type[ApiJobSource]] = [AdzunaSource, ReedSource]
