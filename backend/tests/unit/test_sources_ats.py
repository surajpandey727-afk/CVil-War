"""Adapter defects that corrupted "Open job" and starved the fit analysis.

All three were found by probing the live endpoints, not by reading the code, and all three
were silent: they produced plausible rows that were simply wrong.
"""

from __future__ import annotations

from app.core.job_discovery.sources.ats import LeverSource, SmartRecruitersSource


class TestSmartRecruitersPostingUrl:
    """`ref` is the API self-link. Storing it as the job URL sent the operator to raw JSON."""

    def test_the_url_is_a_human_viewable_page_not_the_api_self_link(self) -> None:
        src = SmartRecruitersSource()
        src.board_token = "Wise"
        src.company_name = "Wise"
        listing = src._to_listing({
            "id": "744000143430928",
            "name": "FinCrime Operations Analyst",
            "ref": "https://api.smartrecruiters.com/v1/companies/Wise/postings/744000143430928",
            "location": {"city": "London", "country": "uk"},
        })

        assert listing is not None
        assert listing.url == "https://jobs.smartrecruiters.com/Wise/744000143430928"
        assert "api.smartrecruiters.com" not in listing.url

    def test_the_free_metadata_the_list_already_returns_is_kept(self) -> None:
        """industry, function, department and seniority arrive in the same response that was
        already being fetched, and were being thrown away into an empty dict."""
        src = SmartRecruitersSource()
        src.board_token = "Wise"
        listing = src._to_listing({
            "id": "1",
            "name": "Analyst",
            "location": {},
            "industry": {"id": "financial_services", "label": "Financial Services"},
            "function": {"label": "Finance"},
            "department": {"label": "FinCrime"},
            "experienceLevel": {"label": "Mid-Senior Level"},
        })

        assert listing is not None
        assert listing.raw_data["industry"] == "Financial Services"
        assert listing.raw_data["function"] == "Finance"
        assert listing.raw_data["department"] == "FinCrime"
        assert listing.raw_data["experience_level"] == "Mid-Senior Level"

    def test_the_list_endpoint_carries_no_description_and_none_is_invented(self) -> None:
        """The old code read a `jobAd` key that the list response does not have, so every
        SmartRecruiters job was stored with an empty description — and then scored against
        nothing. Empty is now explicit; the text comes from the detail endpoint on demand."""
        src = SmartRecruitersSource()
        src.board_token = "Wise"
        listing = src._to_listing({"id": "1", "name": "Analyst", "location": {}})

        assert listing is not None
        assert listing.description == ""


class TestLeverApplyUrl:
    def test_the_apply_url_is_actually_written_so_the_fallback_works(self) -> None:
        """`get_application_url` read raw_data["apply_url"], which nothing ever set — dead
        code that silently returned the posting URL for every Lever job."""
        src = LeverSource()
        src.company_name = "Palantir"
        listing = src._to_listing({
            "id": "abc",
            "text": "Engineer",
            "hostedUrl": "https://jobs.lever.co/palantir/abc",
            "applyUrl": "https://jobs.lever.co/palantir/abc/apply",
            "categories": {"location": "London"},
        })

        assert listing is not None
        assert listing.raw_data["apply_url"] == "https://jobs.lever.co/palantir/abc/apply"
        assert src.get_application_url(listing).endswith("/apply")

    def test_a_posting_with_no_apply_url_falls_back_to_the_posting(self) -> None:
        src = LeverSource()
        listing = src._to_listing({
            "id": "abc", "text": "Engineer",
            "hostedUrl": "https://jobs.lever.co/palantir/abc",
            "categories": {"location": "London"},
        })
        assert listing is not None
        assert src.get_application_url(listing) == "https://jobs.lever.co/palantir/abc"
