"""The canonical fields the job API serves alongside the posting's own text.

`salary_range` is free text and `sponsor_confidence` is a five-way evidence grade. Neither can
be filtered or bucketed without being read first, and every consumer that read them for itself
got a different answer -- a card showing "£60,000" sitting in a list a £50k filter had just
removed it from. These assert that the read form travels with the response, so there is one
answer rather than one per consumer.
"""

from datetime import UTC, datetime

from app.models.enums import SponsorConfidence
from app.schemas.job import JobListingResponse, sponsorship_status


def listing(**overrides) -> JobListingResponse:
    base = {
        "id": "j1",
        "platform": "reed",
        "platform_job_id": "r1",
        "title": "ML Engineer",
        "company": "Northwind",
        "location": "London",
        "url": "https://example.invalid/j1",
        "description": "",
        "status": "new",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    return JobListingResponse(**{**base, **overrides})


class TestSalaryFields:
    def test_a_published_range_arrives_as_numbers(self):
        job = listing(salary_range="£90,000 - £110,000")
        assert job.salary_min == 90_000
        assert job.salary_max == 110_000
        assert job.salary_currency == "GBP"
        assert job.salary_period == "year"
        assert job.salary_annualised is False

    def test_the_postings_own_words_are_still_served(self):
        # The derived band never replaces what the employer wrote. A candidate reading
        # "£110k" wants to be able to check it against the advert.
        job = listing(salary_range="Up to £60,000 + 10% bonus")
        assert job.salary_range == "Up to £60,000 + 10% bonus"
        assert job.salary_max == 60_000
        assert job.salary_min is None

    def test_a_day_rate_is_flagged_as_converted_rather_than_quoted(self):
        job = listing(salary_range="£500 per day")
        assert job.salary_min == 110_000
        assert job.salary_period == "day"
        assert job.salary_annualised is True

    def test_an_unpublished_salary_is_null_not_zero(self):
        # Zero would put every job that does not advertise pay below every minimum a
        # candidate could set, which on most UK boards is the majority of them.
        job = listing(salary_range="Competitive")
        assert job.salary_min is None
        assert job.salary_max is None

    def test_a_missing_salary_line_does_not_break_the_response(self):
        job = listing(salary_range=None)
        assert job.salary_min is None
        assert job.salary_currency is None


class TestSponsorshipStatus:
    def test_positive_evidence_is_available(self):
        for grade in (
            SponsorConfidence.CONFIRMED_REGISTER,
            SponsorConfidence.KEYWORD_DETECTED,
            SponsorConfidence.LIKELY,
        ):
            assert sponsorship_status(grade) == "available"

    def test_an_explicit_refusal_is_none(self):
        assert sponsorship_status(SponsorConfidence.NOT_SPONSOR) == "none"

    def test_silence_is_its_own_answer(self):
        # A posting that never mentions sponsorship has not refused it. Collapsing the two
        # would hide most of the market from a candidate who needs a visa.
        assert sponsorship_status(SponsorConfidence.UNKNOWN) == "not_specified"

    def test_every_grade_maps_to_something(self):
        # A new grade added to the enum without a rule here would silently become
        # "not_specified" for candidates who depend on the answer.
        for grade in SponsorConfidence:
            assert sponsorship_status(grade) in {"available", "not_specified", "none"}

    def test_the_status_travels_on_the_response(self):
        job = listing(sponsor_confidence=SponsorConfidence.CONFIRMED_REGISTER)
        assert job.sponsorship_status == "available"

    def test_the_evidence_grade_is_still_served_alongside_it(self):
        # The filter needs the three-way answer; the drawer still shows *why*.
        job = listing(
            sponsor_confidence=SponsorConfidence.KEYWORD_DETECTED,
            sponsor_evidence="visa sponsorship available",
        )
        assert job.sponsor_confidence == SponsorConfidence.KEYWORD_DETECTED
        assert job.sponsor_evidence == "visa sponsorship available"
        assert job.sponsorship_status == "available"

    def test_the_default_is_the_honest_one(self):
        assert listing().sponsorship_status == "not_specified"
