"""Strict location filtering for stored jobs.

The bug this fixes, verbatim from the product: searching "AI Product Manager" in "London, UK"
returned an accounts-payable role in the USA, a Worldwide office assistant, and a Europe-wide
sales role. Every test here is a case that has to keep working for that not to come back.
"""

from __future__ import annotations

import pytest

from app.core.job_discovery.location import (
    is_country_wide,
    location_matches,
    resolve_city,
)


class TestLondonIsRecognised:
    @pytest.mark.parametrize(
        "job_location",
        [
            "London",
            "London, UK",
            "London, England",
            "Greater London",
            "Central London",
            "City of London",
            "london",  # boards are inconsistent about case
            "LONDON",
            "London, United Kingdom",
            "Hybrid - London",
            "London (Hybrid)",
            "Remote — London",
            "South London",
        ],
    )
    def test_the_obvious_spellings_all_match(self, job_location: str) -> None:
        assert location_matches("London", job_location) is True

    @pytest.mark.parametrize(
        "job_location",
        ["Camden", "Southwark", "Tower Hamlets", "Canary Wharf", "Shoreditch",
         "Westminster", "Hackney", "Richmond upon Thames", "Kings Cross"],
    )
    def test_a_borough_or_district_is_a_london_job(self, job_location: str) -> None:
        """Adverts routinely name the area and never write "London". Rejecting those is the
        same false negative, one level down."""
        assert location_matches("London", job_location) is True

    @pytest.mark.parametrize("job_location", ["EC4N 6EU", "EC4N6EU", "SW1A 1AA", "N1 9GU"])
    def test_a_postcode_only_advert_is_matched(self, job_location: str) -> None:
        """Reed gives postcodes with no city at all — 'EC4N6EU' is a real observed value."""
        assert location_matches("London", job_location) is True

    def test_the_filter_text_may_carry_a_country_too(self) -> None:
        """The search box is prefilled with "London, UK"; that must behave as London."""
        assert location_matches("London, UK", "Shoreditch") is True
        assert location_matches("London, England", "Camden") is True


class TestCountryWidePostingsAreExcluded:
    """The specific complaint: a London filter returning UK-wide and Worldwide jobs."""

    @pytest.mark.parametrize(
        "job_location",
        ["UK", "United Kingdom", "England", "Remote", "Remote UK", "UK Remote",
         "Worldwide", "Europe", "EMEA", "Anywhere", "Nationwide", "Multiple Locations",
         "Home Based", "Work From Home"],
    )
    def test_a_country_or_region_does_not_satisfy_a_city_filter(self, job_location) -> None:  # type: ignore[no-untyped-def]
        assert location_matches("London", job_location) is False

    @pytest.mark.parametrize(
        "job_location",
        ["USA", "Cleveland, OH", "Manchester", "Birmingham", "Dublin, Ireland",
         "Berlin, Germany", "New York, NY"],
    )
    def test_another_place_never_matches(self, job_location: str) -> None:
        assert location_matches("London", job_location) is False

    def test_a_remote_job_naming_no_city_is_not_a_london_job(self) -> None:
        """`remote=True` must not be a free pass. A Worldwide remote role is exactly what the
        operator was complaining about seeing in a London search."""
        assert location_matches("London", "Worldwide", remote=True) is False
        assert location_matches("London", "", remote=True) is False

    def test_a_remote_job_that_does_name_london_still_matches(self) -> None:
        """It matches on the city, not on the remoteness."""
        assert location_matches("London", "Remote, London", remote=True) is True

    def test_a_blank_job_location_is_not_a_match(self) -> None:
        """Unknown is not London. Treating an empty string as a match would let every
        location-less listing through the filter."""
        assert location_matches("London", "") is False


class TestOtherCitiesDoNotBleed:
    def test_manchester_filters_to_manchester(self) -> None:
        assert location_matches("Manchester", "Manchester, UK") is True
        assert location_matches("Manchester", "London") is False

    def test_a_non_london_postcode_is_not_read_as_london(self) -> None:
        """"M1" and "B15" have the same letter-digit shape as a London outward code."""
        assert location_matches("London", "M1 4AB") is False
        assert location_matches("London", "B15 2TT") is False
        assert location_matches("London", "LS1 4DY") is False


class TestBroadFiltersStayBroad:
    """Asking for something broad is a legitimate request, not a mistake to correct."""

    def test_filtering_by_uk_matches_uk_postings(self) -> None:
        assert location_matches("United Kingdom", "United Kingdom") is True
        assert location_matches("UK", "London, UK") is True

    def test_an_empty_filter_matches_everything(self) -> None:
        assert location_matches("", "Anywhere") is True
        assert location_matches("   ", "Cleveland, OH") is True

    def test_an_unknown_place_still_filters_rather_than_returning_nothing(self) -> None:
        """A place not in the table falls back to substring. Refusing to filter at all would
        silently show every job; returning nothing would look like "no jobs exist"."""
        assert location_matches("Reykjavik", "Reykjavik, Iceland") is True
        assert location_matches("Reykjavik", "London") is False


class TestHelpers:
    def test_resolve_city_reads_the_operators_text(self) -> None:
        assert resolve_city("London, UK").key == "London".lower()  # type: ignore[union-attr]
        assert resolve_city("Canary Wharf").key == "london"  # type: ignore[union-attr]
        assert resolve_city("United Kingdom") is None
        assert resolve_city("") is None

    def test_is_country_wide_is_all_parts_not_any(self) -> None:
        """"London, UK" contains a country-wide term but is not country-wide. Using `any`
        here would have excluded the single most common London spelling there is."""
        assert is_country_wide("UK") is True
        assert is_country_wide("Remote, UK") is True
        assert is_country_wide("London, UK") is False
