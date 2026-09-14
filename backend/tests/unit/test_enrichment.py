"""Pulling requirements out of a posting.

Every bug fixed here was invisible in exactly the same way: the job reported no requirements,
which is indistinguishable from a posting that genuinely lists none. Nothing errored, nothing
logged, and the fit analysis downstream confidently assessed nothing at all.
"""
# ruff: noqa: RUF001
# Curly quotes and bullets appear deliberately: they are what real postings use,
# and substituting ASCII look-alikes would stop exercising the case under test.

from __future__ import annotations

import pytest

from app.services.enrichment import extract_sections, normalise, years_required

BULLETED = """About the role
We are building something good.

What We're Looking For
• 5+ years of product management experience in a B2B setting
• Experience shipping machine-learning products to production
• Strong written communication

What We Offer
• Private medical cover
• 28 days holiday plus bank holidays
"""


class TestTypographicPunctuation:
    """Curly apostrophes silently defeated every heading pattern."""

    def test_a_curly_apostrophe_heading_is_recognised(self) -> None:
        posting = BULLETED.replace("We're", "We’re")
        assert extract_sections(posting)["requirements"], (
            "a posting using a typographic apostrophe found no requirements"
        )

    def test_normalise_folds_the_punctuation_postings_actually_use(self) -> None:
        assert normalise("We’re") == "We're"
        assert normalise("“quoted”") == '"quoted"'
        assert normalise("a–b") == "a-b"

    def test_a_straight_apostrophe_still_works(self) -> None:
        assert extract_sections(BULLETED)["requirements"]


class TestSectionBoundaries:
    def test_requirements_are_taken_verbatim(self) -> None:
        requirements = extract_sections(BULLETED)["requirements"]
        assert any("5+ years of product management" in r for r in requirements)
        assert any("machine-learning products" in r for r in requirements)

    def test_benefits_are_separated_from_requirements(self) -> None:
        sections = extract_sections(BULLETED)
        assert any("Private medical" in b for b in sections["benefits"])
        assert not any("Private medical" in r for r in sections["requirements"])

    def test_a_heading_is_not_itself_a_requirement(self) -> None:
        requirements = extract_sections(BULLETED)["requirements"]
        assert "What We're Looking For" not in requirements

    def test_a_closing_heading_ends_the_section(self) -> None:
        """Without this, the company blurb and the interview process are collected as
        requirements — the posting ends up "asking for" its own equal-opportunity notice."""
        posting = BULLETED + """
About Us
• We were founded in 2015 and have offices in three countries
• We are an equal opportunities employer
"""
        requirements = extract_sections(posting)["requirements"]
        assert not any("founded in 2015" in r for r in requirements)
        assert not any("equal opportunities" in r for r in requirements)

    def test_prose_before_any_heading_is_not_a_requirement(self) -> None:
        assert not any(
            "building something good" in r for r in extract_sections(BULLETED)["requirements"]
        )


class TestLineStructure:
    def test_a_posting_written_as_lines_is_split_on_lines(self) -> None:
        """The HTML-to-text step preserves list items as their own lines; using that beats any
        punctuation heuristic, and flattening it was what broke extraction originally."""
        sections = extract_sections(BULLETED)
        assert len(sections["requirements"]) == 3

    def test_a_posting_written_as_one_run_of_prose_still_yields_lines(self) -> None:
        prose = (
            "Requirements. You will have 6 years of experience in product. "
            "You will have shipped data products. You will write clearly."
        )
        assert extract_sections(prose)["requirements"]

    def test_an_empty_posting_yields_nothing_rather_than_failing(self) -> None:
        assert extract_sections("") == {"requirements": [], "benefits": []}
        assert extract_sections("   \n  ") == {"requirements": [], "benefits": []}


class TestExperienceBar:
    def test_the_highest_stated_figure_wins(self) -> None:
        """A posting wanting "3+ years product and 5+ years regulated" is a five-year posting;
        reporting three would understate the bar the operator is measured against."""
        assert years_required(["3+ years in product", "5+ years in a regulated domain"]) == 5

    def test_a_years_line_counts_wherever_it_appears(self) -> None:
        """Postings routinely state the hard bar outside any labelled section."""
        posting = "About the role\nYou will need 7 years of experience.\nAbout Us\nWe are nice."
        assert any("7 years" in r for r in extract_sections(posting)["requirements"])

    def test_a_posting_that_never_says_reports_nothing(self) -> None:
        """Not "0 years" — the posting simply did not say, and inventing a floor would be a
        fabricated requirement."""
        assert years_required(["Strong communication skills"]) is None
        assert years_required([]) is None

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("5+ years", 5),
            ("3-5 years of experience", 3),
            ("10 years", 10),
            ("2 Years experience", 2),
        ],
    )
    def test_year_phrasings_postings_actually_use(self, line: str, expected: int) -> None:
        assert years_required([line]) == expected


class TestBoundsAreSane:
    def test_a_very_long_paragraph_is_not_a_requirement_line(self) -> None:
        posting = "Requirements\n" + ("word " * 200)
        assert extract_sections(posting)["requirements"] == []

    def test_a_fragment_is_not_a_requirement_line(self) -> None:
        posting = "Requirements\n• ok\n• 5+ years of genuine product experience here"
        requirements = extract_sections(posting)["requirements"]
        assert not any(r == "ok" for r in requirements)

    def test_duplicate_lines_are_collapsed(self) -> None:
        posting = "Requirements\n• 5+ years of product\n• 5+ years of product"
        assert len(extract_sections(posting)["requirements"]) == 1

    def test_the_lists_are_capped(self) -> None:
        posting = "Requirements\n" + "\n".join(
            f"• Requirement number {i} with enough length to count" for i in range(60)
        )
        assert len(extract_sections(posting)["requirements"]) <= 30
