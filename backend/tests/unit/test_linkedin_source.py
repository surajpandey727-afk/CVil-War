"""LinkedIn discovery.

Parsing someone else's markup is inherently fragile, so these tests fix the behaviours that
were established by observation against the live endpoint — particularly the two that were
wrong on the first attempt and would have shipped silently.
"""

from __future__ import annotations

import pytest

from app.core.job_discovery.sources.linkedin import LinkedInSource, _salary_band

CARD = """
<li>
  <div class="base-card" data-entity-urn="urn:li:jobPosting:{jid}">
    <a class="base-card__full-link" href="https://uk.linkedin.com/jobs/view/pm-at-monzo-{jid}?refId=x">
    <h3 class="base-search-card__title"> {title} </h3>
    <h4 class="base-search-card__subtitle"><a href="#"> {company} </a></h4>
    <span class="job-search-card__location"> {location} </span>
    <time datetime="2026-08-01"></time>
    {salary}
  </div>
</li>
"""

SALARY = '<div class="job-search-card__salary-info"> £60,000 - £75,000 </div>'


def page(*cards: str) -> str:
    return "<ul>" + "".join(cards) + "</ul>"


def card(jid="1", title="Product Manager", company="Monzo", location="London, England",
         salary="") -> str:
    return CARD.format(jid=jid, title=title, company=company, location=location, salary=salary)


@pytest.fixture
def source() -> LinkedInSource:
    return LinkedInSource()


class TestCardParsing:
    def test_a_card_yields_every_field_it_carries(self, source: LinkedInSource) -> None:
        [record] = source._parse_cards(page(card(salary=SALARY)))

        assert record["job_id"] == "1"
        assert record["title"] == "Product Manager"
        assert record["company"] == "Monzo"
        assert record["location"] == "London, England"
        assert record["posted_at"] == "2026-08-01"
        assert "60,000" in record["salary"]

    def test_a_card_without_a_salary_does_not_borrow_the_next_one(
        self, source: LinkedInSource
    ) -> None:
        """The defect this pins: running each pattern across the whole page instead of per
        card shifts every later salary up by one, attaching real money to the wrong job."""
        records = source._parse_cards(page(
            card(jid="1", title="No Salary Role"),
            card(jid="2", title="Paid Role", salary=SALARY),
        ))

        assert records[0]["salary"] == ""
        assert "60,000" in records[1]["salary"]

    def test_a_card_missing_its_id_or_title_is_skipped(self, source: LinkedInSource) -> None:
        assert source._parse_cards("<ul><li><div>nothing useful</div></li></ul>") == []

    def test_entities_are_decoded_rather_than_shown_raw(self, source: LinkedInSource) -> None:
        [record] = source._parse_cards(page(card(company="Marks &amp; Spencer")))
        assert record["company"] == "Marks & Spencer"

    def test_an_empty_page_yields_nothing(self, source: LinkedInSource) -> None:
        assert source._parse_cards("") == []


class TestNormalisation:
    def test_a_listing_carries_a_stable_permalink(self, source: LinkedInSource) -> None:
        [record] = source._parse_cards(page(card(jid="998")))
        listing = source._to_listing(record)

        assert listing is not None
        assert listing.platform == "linkedin"
        assert "998" in listing.url
        # The tracking query must not survive into the stored record.
        assert "refId" not in listing.url

    def test_a_record_without_a_title_is_dropped(self, source: LinkedInSource) -> None:
        assert source._to_listing({"job_id": "1", "title": ""}) is None
        assert source._to_listing({"job_id": "", "title": "PM"}) is None

    def test_the_application_url_points_at_the_posting(self, source: LinkedInSource) -> None:
        [record] = source._parse_cards(page(card(jid="4321")))
        listing = source._to_listing(record)
        assert listing is not None
        assert source.get_application_url(listing).endswith("/jobs/view/4321/")


class TestSalary:
    def test_a_band_is_read_as_a_band(self) -> None:
        assert _salary_band("£60,000 - £75,000") == (60000.0, 75000.0, "GBP")

    def test_a_single_figure_is_a_floor_not_a_band(self) -> None:
        assert _salary_band("£60,000") == (60000.0, None, "GBP")

    def test_an_absent_salary_stays_absent(self) -> None:
        """Inventing a midpoint would feed a fabricated number into ranking."""
        assert _salary_band("") == (None, None, "GBP")
        assert _salary_band("Competitive") == (None, None, "GBP")

    @pytest.mark.parametrize(
        ("text", "currency"), [("$120,000", "USD"), ("€80,000", "EUR"), ("£70,000", "GBP")]
    )
    def test_the_currency_comes_from_the_symbol(self, text: str, currency: str) -> None:
        assert _salary_band(text)[2] == currency


class TestGeographyIsNotTrusted:
    """LinkedIn returned Milton Keynes, Cambridge and Reading for a London search."""

    def test_the_source_declares_that_it_does_not_filter_geography(self) -> None:
        # If this ever flips to True the strict post-filter stops running and the London bug
        # returns on this source.
        assert LinkedInSource.server_side_location is False

    @pytest.mark.parametrize(
        "elsewhere", ["Milton Keynes, England", "Cambridge, England", "Reading, England"]
    )
    def test_a_role_outside_the_requested_city_is_rejected(
        self, source: LinkedInSource, elsewhere: str
    ) -> None:
        [record] = source._parse_cards(page(card(location=elsewhere)))
        listing = source._to_listing(record)
        assert listing is not None
        assert not source._post_filter(listing, "product manager", "London, United Kingdom")

    @pytest.mark.parametrize(
        "london",
        ["London, England, United Kingdom", "City Of London, England", "Greater London, England"],
    )
    def test_a_london_role_survives_however_it_is_written(
        self, source: LinkedInSource, london: str
    ) -> None:
        [record] = source._parse_cards(page(card(location=london)))
        listing = source._to_listing(record)
        assert listing is not None
        assert source._post_filter(listing, "product manager", "London, United Kingdom")

    def test_an_empty_location_filter_keeps_everything(self, source: LinkedInSource) -> None:
        [record] = source._parse_cards(page(card(location="Berlin, Germany")))
        listing = source._to_listing(record)
        assert listing is not None
        assert source._post_filter(listing, "", "")


class TestPolitenessIsStructural:
    def test_a_rate_limit_is_reported_rather_than_retried(self) -> None:
        """Hammering through a 429 is what gets a source blocked outright."""
        import inspect

        source = inspect.getsource(LinkedInSource._page)
        assert "429" in source
        assert "SourceUnavailableError" in source
        assert "retry" not in source.lower()

    def test_pages_are_paced_and_bounded(self) -> None:
        from app.core.job_discovery.sources import linkedin

        assert linkedin._PAGE_DELAY >= 1.0
        assert linkedin._DETAIL_DELAY >= 5.0
        assert linkedin._MAX_PAGES <= 10

    def test_the_health_probe_is_cheaper_than_a_search(self) -> None:
        """The inherited probe ran a full ten-page search and timed out the verification
        sweep, so a working source reported "no answer within 25s"."""
        import inspect

        source = inspect.getsource(LinkedInSource.health_check)
        assert "_page(" in source
        assert "_add_descriptions" not in source
