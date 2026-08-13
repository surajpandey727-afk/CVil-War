"""Adzuna and Reed adapters.

Two classes of bug are pinned here, both found against the live APIs rather than by reading
the code, and both silent — they produced plausible-looking results that were simply wrong.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import Settings
from app.core.job_discovery.sources.base import CostType
from app.core.job_discovery.sources.uk_boards import (
    DEFAULT_RADIUS_MILES,
    MAX_RADIUS_MILES,
    AdzunaSource,
    ReedSource,
    miles_to_km,
)

ADZUNA_RECORD = {
    "id": "5822250371",
    "title": "Productivity Manager",
    "company": {"display_name": "Anson McCade"},
    "location": {"display_name": "London, UK"},
    "redirect_url": "https://www.adzuna.co.uk/jobs/land/ad/5822250371",
    "description": "<p>Lead the <b>product</b> function.</p>",
    "salary_min": 75000,
    "salary_max": 95000,
    "salary_is_predicted": "1",
    "created": "2026-07-31T11:12:29Z",
    "category": {"label": "IT Jobs"},
}

REED_RECORD = {
    "jobId": 56654149,
    "jobTitle": "CRM - Product Owner",
    "employerName": "FRP Group",
    "locationName": "EC4N6EU",
    "jobDescription": "<p>Own the CRM roadmap.</p>",
    "minimumSalary": 60000,
    "maximumSalary": 70000,
    "currency": "GBP",
    "date": "16/03/2026",
    "jobUrl": "https://www.reed.co.uk/jobs/crm-product-owner/56654149",
    "employerId": 123,
    "applications": 4,
}


def _client(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    return client


class TestRadiusUnits:
    """Reed's radius is miles, Adzuna's is kilometres — and nothing in either response says so."""

    def test_miles_convert_to_kilometres(self) -> None:
        assert miles_to_km(30) == 49  # 48.28 km, rounded up
        assert miles_to_km(5) == 9

    def test_conversion_rounds_up_not_down(self) -> None:
        """Rounding down would silently exclude jobs at the edge of the requested radius;
        rounding up returns a few extra rows the operator can simply ignore."""
        assert miles_to_km(10) >= 10 * 1.609

    @pytest.mark.asyncio
    async def test_adzuna_sends_kilometres(self) -> None:
        src = AdzunaSource()
        src._radius = 30
        cfg = Settings()
        cfg.adzuna_app_id = MagicMock(get_secret_value=lambda: "id")
        cfg.adzuna_app_key = MagicMock(get_secret_value=lambda: "key")
        client = _client({"results": []})
        with patch("app.core.job_discovery.sources.uk_boards.get_settings", return_value=cfg):
            await src._fetch(client, "product manager", "London", 50)
        params = client.get.call_args.kwargs["params"]
        assert params["distance"] == 49, "30 miles must be sent to Adzuna as 49 km"

    @pytest.mark.asyncio
    async def test_reed_sends_miles_unconverted(self) -> None:
        src = ReedSource()
        src._radius = 30
        src._filters = {}
        cfg = Settings()
        cfg.reed_api_key = MagicMock(get_secret_value=lambda: "key")
        client = _client({"results": []})
        with patch("app.core.job_discovery.sources.uk_boards.get_settings", return_value=cfg):
            await src._fetch(client, "product manager", "London", 50)
        params = client.get.call_args.kwargs["params"]
        assert params["distanceFromLocation"] == 30, "Reed takes miles directly"


class TestServerSideFilteringIsNotDuplicated:
    """Re-filtering a server-side result discards matches the API deliberately made.

    Observed live: Adzuna returns everything within N miles of London including Hertfordshire
    and Surrey. Re-checking those place names against a London alias list cut a 50-result
    broad browse down to 12, and made a 30-mile radius return FEWER jobs than a 5-mile one.
    """

    def test_both_uk_sources_declare_server_side_filtering(self) -> None:
        for cls in (AdzunaSource, ReedSource):
            assert cls.server_side_search is True
            assert cls.server_side_location is True

    def test_a_result_outside_the_named_city_is_kept(self) -> None:
        """A commuter-belt town is a valid result for a 30-mile London search."""
        src = AdzunaSource()
        listing = src._to_listing({**ADZUNA_RECORD, "location": {"display_name": "Watford"}})
        assert listing is not None
        assert src._post_filter(listing, "product manager", "London") is True

    def test_a_loosely_matching_title_is_kept(self) -> None:
        """Reed's search does stemming and synonyms; a stricter local word match would throw
        away rows the engine matched on purpose."""
        src = ReedSource()
        listing = src._to_listing(REED_RECORD)  # "CRM - Product Owner"
        assert listing is not None
        assert src._post_filter(listing, "AI Product Manager", "London") is True


class TestNormalisation:
    def test_adzuna_record_maps_to_the_canonical_model(self) -> None:
        listing = AdzunaSource()._to_listing(ADZUNA_RECORD)
        assert listing is not None
        assert listing.platform == "adzuna"
        assert listing.company == "Anson McCade"
        assert listing.salary_min == 75000
        assert listing.salary_currency == "GBP"
        assert "<p>" not in listing.description, "HTML must be flattened for the ATS analyser"

    def test_adzuna_predicted_salary_is_flagged_not_presented_as_published(self) -> None:
        """Adzuna infers a salary when the advert omits one; losing that flag would show a
        guess to the user as though the employer had published it."""
        listing = AdzunaSource()._to_listing(ADZUNA_RECORD)
        assert listing is not None
        assert listing.raw_data["salary_is_predicted"] == "1"

    def test_reed_record_maps_to_the_canonical_model(self) -> None:
        listing = ReedSource()._to_listing(REED_RECORD)
        assert listing is not None
        assert listing.platform == "reed"
        assert listing.platform_job_id == "56654149"
        assert listing.company == "FRP Group"
        assert listing.url.startswith("https://www.reed.co.uk/jobs/")


class TestCredentialsAndCost:
    def test_neither_source_can_bill(self) -> None:
        """Free tiers with no card on file. If either ever gains overage billing this must
        change to OPTIONAL_PAID, which ZERO_COST_MODE then disables by default."""
        for cls in (AdzunaSource, ReedSource):
            assert cls.cost_type is CostType.FREE
            assert cls.estimated_cost == 0.0

    @pytest.mark.asyncio
    async def test_a_missing_key_yields_no_results_rather_than_an_error(self) -> None:
        """An unconfigured source must not take the whole multi-source run down with it."""
        cfg = Settings()
        cfg.adzuna_app_id = MagicMock(get_secret_value=lambda: "")
        cfg.adzuna_app_key = MagicMock(get_secret_value=lambda: "")
        src = AdzunaSource()
        src._radius = 30
        with patch("app.core.job_discovery.sources.uk_boards.get_settings", return_value=cfg):
            assert await src._fetch(_client({"results": []}), "x", "London", 10) == []

    def test_both_declare_they_need_a_credential(self) -> None:
        for cls in (AdzunaSource, ReedSource):
            assert cls().capabilities()["needs_credential"] is True


class TestRadiusClamping:
    @pytest.mark.asyncio
    async def test_radius_is_clamped_to_the_supported_maximum(self) -> None:
        from app.core.job_discovery.sources.uk_boards import _radius_miles

        assert _radius_miles({"radius_miles": 500}) == MAX_RADIUS_MILES
        assert _radius_miles({"radius_miles": 0}) == DEFAULT_RADIUS_MILES
        assert _radius_miles({"radius_miles": "not a number"}) == DEFAULT_RADIUS_MILES
        assert _radius_miles(None) == DEFAULT_RADIUS_MILES
