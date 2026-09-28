"""The salary parser, against the postings that broke its predecessor.

Every case in `test_the_regressions_that_motivated_this` is a real salary line from a UK job
board that the previous "smallest number in the string" reader got wrong -- in the direction
that costs the candidate a role. They are the reason this module exists, so they are the first
thing it is asserted against.
"""

import pytest

from app.core.salary import DAYS_PER_YEAR, HOURS_PER_YEAR, parse_salary


class TestPublishedBands:
    def test_reads_a_plain_range(self):
        band = parse_salary("£90,000 - £110,000")
        assert (band.minimum, band.maximum) == (90_000, 110_000)
        assert band.currency == "GBP"
        assert band.annualised is False

    def test_reads_a_k_shorthand_range(self):
        band = parse_salary("£45k - £55k")
        assert (band.minimum, band.maximum) == (45_000, 55_000)

    def test_reads_a_range_with_no_currency_marker(self):
        band = parse_salary("80000-95000")
        assert (band.minimum, band.maximum) == (80_000, 95_000)
        assert band.currency is None

    def test_a_single_figure_is_both_ends_of_the_band(self):
        band = parse_salary("£72,500")
        assert (band.minimum, band.maximum) == (72_500, 72_500)

    def test_keeps_the_currency_the_posting_used(self):
        assert parse_salary("$120,000 - $150,000").currency == "USD"
        assert parse_salary("€80,000").currency == "EUR"
        assert parse_salary("GBP 95,000").currency == "GBP"


class TestUnpublished:
    @pytest.mark.parametrize("text", ["Competitive", "DOE", "", None, "Negotiable", "  "])
    def test_no_figure_means_no_band_rather_than_zero(self, text):
        band = parse_salary(text)
        assert band.published is False
        assert band.minimum is None and band.maximum is None

    def test_zero_would_have_excluded_every_job_that_does_not_advertise_pay(self):
        # The distinction this file exists to protect: "not published" is not "£0". Most UK
        # postings publish nothing, so conflating them hides the majority of the market behind
        # any minimum-salary filter at all.
        assert parse_salary("Competitive salary and benefits").minimum is None


class TestTheRegressionsThatMotivatedThis:
    def test_a_bonus_percentage_is_not_the_salary(self):
        # Previously: £10k. A "minimum £50k" filter hid this £60k role.
        band = parse_salary("Up to £60,000 + 10% bonus")
        assert band.maximum == 60_000
        assert band.minimum is None  # "up to" states a ceiling, not a floor

    def test_a_holiday_allowance_is_not_the_salary(self):
        # Previously: £25k.
        band = parse_salary("£65,000 per annum, 25 days holiday")
        assert (band.minimum, band.maximum) == (65_000, 65_000)

    def test_a_pension_contribution_is_not_the_salary(self):
        band = parse_salary("£58,000 plus 8% pension")
        assert band.minimum == 58_000

    def test_a_day_rate_is_annualised_rather_than_read_as_an_annual_figure(self):
        # Previously: £500k, which sorted this contract above every permanent role on screen.
        band = parse_salary("£500 per day")
        assert band.minimum == 500 * DAYS_PER_YEAR
        assert band.period == "day"
        assert band.annualised is True

    def test_a_day_rate_written_with_a_slash_and_an_ir35_note(self):
        # Previously: £1.2k, because "1,200" lost its thousands separator and "35" won.
        band = parse_salary("£1,200/day outside IR35")
        assert band.minimum == 1_200 * DAYS_PER_YEAR
        assert band.annualised is True

    def test_an_hourly_rate_is_annualised(self):
        band = parse_salary("£55 - £65 per hour")
        assert (band.minimum, band.maximum) == (55 * HOURS_PER_YEAR, 65 * HOURS_PER_YEAR)
        assert band.period == "hour"

    def test_a_monthly_figure_is_annualised_and_not_mistaken_for_a_year(self):
        band = parse_salary("£6,500 per month")
        assert band.minimum == 78_000
        assert band.annualised is True

    def test_years_of_experience_is_not_a_salary(self):
        assert parse_salary("£85,000 — 5 years experience required").minimum == 85_000

    def test_a_visa_tier_is_not_a_salary(self):
        assert parse_salary("£48,000, Tier 2 sponsorship available").minimum == 48_000


class TestCredibility:
    def test_a_figure_far_below_any_salary_is_not_reported_as_one(self):
        assert parse_salary("£250 referral bonus").published is False

    def test_an_implausibly_large_figure_is_rejected(self):
        assert parse_salary("£50,000,000 funding round").published is False

    def test_a_small_bare_number_is_not_money(self):
        assert parse_salary("5 stage interview process").published is False


class TestDirectionalPhrases:
    def test_up_to_sets_only_a_ceiling(self):
        band = parse_salary("Up to £95,000")
        assert band.minimum is None and band.maximum == 95_000

    def test_from_sets_only_a_floor(self):
        band = parse_salary("From £70,000")
        assert band.minimum == 70_000 and band.maximum is None
