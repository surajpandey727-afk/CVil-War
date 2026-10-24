"""The UK-only location policy (app.core.geo.classify).

Every location string below is taken verbatim from the production job corpus, which is where
US and EU roles were leaking onto the jobs page. The direction that matters most is the false
positive: a foreign job classified UK is shown to the candidate. So most cases here are the
lookalikes — "Birmingham, AL", "London, ON", "SF, NY, SEA" — that a substring test gets wrong.
"""

import pytest

from app.core.geo import AMBIGUOUS, UNKNOWN, VERIFIED, classify_location


def uk(location: str, platform: str = "careers:stripe", **kw) -> bool:  # type: ignore[no-untyped-def]
    return classify_location(location, platform=platform, **kw).uk_eligible


class TestForeignJobsAreNeverUK:
    @pytest.mark.parametrize(
        "location",
        [
            "San Francisco", "San Francisco, CA", "New York, NY", "US-CA-Menlo Park",
            "Seattle, Washington, United States", "SF, NY, SEA, Remote-US", "NYC, SF",
            "San Francisco, CA � New York, NY � United States", "Toronto",
            "Berlin", "München", "Köln, Nordrhein-Westfalen, Germany", "Zürich, CH", "Paris, France", "Dublin", "Dublin, Ireland",
            "Beijing, cn", "Sydney, au", "Remote - United States", "Remote, Canada; Remote, US",
            "US - Remote", "Doha, Qatar ; Dubai, UAE", "SG-Singapore", "Remote in the US, Chicago",
            "Mapbox Germany", "Greater Chicago Area", "Bengaluru, Karnataka, India, APAC",
        ],
    )  # fmt: skip
    def test_explicitly_foreign_locations_are_verified_non_uk(self, location: str) -> None:
        verdict = classify_location(location, platform="careers:stripe")
        assert verdict.status == VERIFIED
        assert verdict.country_code != "GB"
        assert verdict.uk_eligible is False

    @pytest.mark.parametrize(
        ("location", "country"),
        [
            ("Birmingham, AL", "US"),
            ("Richmond, VA", "US"),
            ("Boston, MA", "US"),
            ("Cambridge, MA", "US"),
            ("London, ON", "CA"),
            ("Manchester, NH", "US"),
        ],
    )
    def test_uk_namesakes_abroad_follow_their_state_or_province(
        self, location: str, country: str
    ) -> None:
        """The British-sounding name must lose to the explicit state code next to it."""
        verdict = classify_location(location, platform="careers:stripe")
        assert verdict.country_code == country
        assert verdict.uk_eligible is False

    def test_a_uk_scoped_board_still_cannot_make_a_foreign_city_uk(self) -> None:
        # Reed does carry the odd overseas role; the posting's own text outranks the board.
        assert uk("Atlanta", platform="reed") is False
        assert uk("Dubai", platform="reed") is False


class TestUKJobsAreVerified:
    @pytest.mark.parametrize(
        ("location", "city"),
        [
            ("London", "London"), ("London, UK", "London"), ("London, gb", "London"),
            ("UK - London", "London"), ("GB-London", "London"),
            ("London, England, United Kingdom", "London"), ("Charing Cross, Central London", "London"),
            ("Greater London, England, United Kingdom", "London"), ("Cambridge, UK", "Cambridge"),
            ("Edinburgh, Scotland", "Edinburgh"), ("Belfast, Northern Ireland", "Belfast"),
            ("Manchester, Greater Manchester", "Manchester"), ("Frimley, Camberley", "Camberley"),
        ],
    )  # fmt: skip
    def test_uk_locations_resolve_city_and_country(self, location: str, city: str) -> None:
        verdict = classify_location(location, platform="adzuna")
        assert verdict.status == VERIFIED
        assert verdict.country_code == "GB"
        assert verdict.country_name == "United Kingdom"
        assert verdict.city == city
        assert verdict.uk_eligible is True

    @pytest.mark.parametrize(
        ("postcode", "city"), [("EC3R8AJ", "London"), ("M37FB", "Manchester"), ("SW1E 5LB", "London")]
    )
    def test_a_full_uk_postcode_is_uk(self, postcode: str, city: str) -> None:
        verdict = classify_location(postcode, platform="reed")
        assert verdict.uk_eligible is True
        assert verdict.city == city
        assert verdict.evidence == "uk_postcode"

    def test_a_multi_location_posting_with_a_uk_office_is_eligible(self) -> None:
        verdict = classify_location("Doha, Qatar; London, UK", platform="careers:scale")
        assert verdict.uk_eligible is True
        assert verdict.city == "London"

    def test_or_joined_remote_uk(self) -> None:
        verdict = classify_location("Cardiff, London or Remote (UK)", platform="careers:monzo")
        assert verdict.uk_eligible is True

    def test_an_unlisted_town_from_a_uk_scoped_board_is_uk(self) -> None:
        verdict = classify_location("Lopenhead", platform="reed")
        assert verdict.uk_eligible is True
        assert verdict.evidence == "uk_scoped_source"


class TestRemoteRoles:
    def test_remote_hiring_in_the_uk_is_eligible(self) -> None:
        verdict = classify_location(
            "Remote, Canada; Remote, United Kingdom; Remote, United States",
            remote=True,
            platform="careers:gitlab",
        )
        assert verdict.uk_eligible is True
        assert verdict.workplace_type == "remote"
        assert "GB" in verdict.remote_eligible_countries

    @pytest.mark.parametrize("location", ["Remote", "Worldwide", "Europe", "Remote-EMEA", "LATAM"])
    def test_remote_without_naming_the_uk_is_quarantined_not_assumed(self, location: str) -> None:
        verdict = classify_location(location, remote=True, platform="remotive")
        assert verdict.status in (AMBIGUOUS, UNKNOWN)
        assert verdict.uk_eligible is False

    def test_remote_uk_and_ireland(self) -> None:
        assert uk("Remote-UK&I", remote=True) is True


class TestAmbiguityIsQuarantined:
    @pytest.mark.parametrize("location", ["Cambridge", "Birmingham", "Plymouth", "Bedford, "])
    def test_a_bare_namesake_from_a_non_uk_board_is_ambiguous(self, location: str) -> None:
        verdict = classify_location(location, platform="arbeitnow")
        assert verdict.status == AMBIGUOUS
        assert verdict.uk_eligible is False

    def test_the_same_namesake_from_a_uk_board_is_uk(self) -> None:
        assert uk("Birmingham", platform="reed") is True

    @pytest.mark.parametrize("location", ["", "N/A", "LOCATION", "Nuremberg-ish place"])
    def test_no_evidence_is_unknown_on_a_global_board(self, location: str) -> None:
        verdict = classify_location(location, platform="careers:stripe")
        assert verdict.uk_eligible is False

    def test_mojibake_from_a_uk_board_is_not_waved_through(self) -> None:
        garbled = "Ù\u0085Ø³Ù\u0082Ø·, Ø¹Ù\u0085"
        assert uk(garbled, platform="reed") is False


class TestEvidenceRules:
    def test_language_is_never_location_evidence(self) -> None:
        # "Homeoffice" is German for remote work; it says nothing about the country.
        assert classify_location("Homeoffice", platform="arbeitnow").country_code is None

    def test_title_supplies_the_work_arrangement_only(self) -> None:
        verdict = classify_location("London", platform="careers:x", title="PM (Hybrid)")
        assert verdict.workplace_type == "hybrid"
        assert verdict.country_code == "GB"

    def test_arrangement_is_unspecified_when_unstated(self) -> None:
        assert classify_location("London").workplace_type == "unspecified"

    def test_deterministic(self) -> None:
        a = classify_location("SF, NY, SEA, Remote-US", platform="careers:stripe")
        b = classify_location("SF, NY, SEA, Remote-US", platform="careers:stripe")
        assert a == b
