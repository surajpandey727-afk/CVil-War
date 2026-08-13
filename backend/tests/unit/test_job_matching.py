"""Relevance and location matching for job discovery.

This logic has been wrong in both directions and each failure is pinned below, because both
were only visible against real listings:

* Too loose — a substring test made the query "ai" match "M(ai)ntenance Technician", and
  matching against job *descriptions* returned an "Inside Sales Contractor" for
  "product manager".
* Too strict — requiring every query term made "AI Product Manager" return *nothing*,
  because almost no title contains all of "ai", "product" and "manager". It rejected
  "Senior Product Manager", the single most obvious match.
"""

from __future__ import annotations

import pytest

from app.core.job_discovery.sources.base import (
    matches_location,
    matches_query,
    relevance,
)


class TestRelevance:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("AI Product Manager", 1.0),          # exact
            ("Product Manager, AI Platform", 1.0),  # reordered
            ("Senior Product Manager", pytest.approx(2 / 3)),  # seniority is filler
            ("Technical Product Manager", pytest.approx(2 / 3)),
            ("Staff Machine Learning Engineer", 0.0),
            ("Maintenance Technician", 0.0),      # the old substring bug
        ],
    )
    def test_scores_against_a_three_term_query(self, title: str, expected: float) -> None:
        assert relevance("AI Product Manager", title) == expected

    def test_filler_words_neither_help_nor_hurt(self) -> None:
        """"Senior" must not count as a matched term, or every senior role scores a point."""
        assert relevance("Senior Product Manager", "Product Manager") == 1.0

    def test_tags_corroborate_but_do_not_substitute_for_the_title(self) -> None:
        strong = relevance("machine learning", "Machine Learning Engineer")
        weak = relevance("machine learning", "Backend Engineer", "machine learning python")
        assert strong == 1.0
        assert 0 < weak < strong


class TestMatchesQuery:
    def test_the_regression_that_returned_zero_results(self) -> None:
        """A PM search must return "Senior Product Manager". This is the whole bug."""
        assert matches_query("AI Product Manager", "Senior Product Manager", "") is True

    def test_a_two_term_query_requires_both_terms(self) -> None:
        """At a 0.5 threshold "Compliance Advisory Manager" matched "Product Manager"
        on the word "Manager" alone, which flooded results with unrelated management roles."""
        assert matches_query("Product Manager", "Compliance Advisory Manager", "") is False
        assert matches_query("Product Manager", "Senior Product Manager", "") is True

    def test_short_acronyms_are_not_matched_as_substrings(self) -> None:
        assert matches_query("ai", "Maintenance Technician", "") is False
        assert matches_query("ai", "AI Engineer", "") is True

    def test_an_empty_query_matches_everything(self) -> None:
        assert matches_query("", "Anything At All", "") is True


class TestMatchesLocation:
    @pytest.mark.parametrize(
        "candidate",
        ["London, UK", "London", "United Kingdom", "Europe", "Greater London"],
    )
    def test_london_accepts_containing_regions(self, candidate: str) -> None:
        """A London search excluding UK-wide and Europe-remote roles is why a located
        search returned almost nothing."""
        assert matches_location("London, UK", candidate, remote=False) is True

    @pytest.mark.parametrize("candidate", ["New York", "Berlin", "Sydney"])
    def test_unrelated_places_are_rejected(self, candidate: str) -> None:
        assert matches_location("London, UK", candidate, remote=False) is False

    def test_a_missing_location_is_unknown_not_elsewhere(self) -> None:
        """Several sources omit the field entirely; excluding them dropped whole sources."""
        assert matches_location("London, UK", "", remote=False) is True

    def test_remote_matches_any_request(self) -> None:
        assert matches_location("London, UK", "Anywhere", remote=True) is True

    def test_an_empty_request_matches_everything(self) -> None:
        assert matches_location("", "Reykjavik", remote=False) is True
