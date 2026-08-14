"""The fit analyser, and above all its anti-fabrication guards.

This is the feature with the worst possible failure mode: telling someone they have
experience they do not, moments before they send a CV to an employer. The tests that matter
most here are the ones that prove a claim without evidence is destroyed rather than displayed.
"""

from __future__ import annotations

import pytest

from app.core.fit.analyzer import (
    LEVEL_WEIGHT,
    attribute,
    build_index,
    build_recommendations,
    overall_score,
    score_categories,
    verify_matches,
)
from app.core.fit.requirements import keyword_requirements
from app.schemas.fit import EvidenceSource, MatchLevel, RequirementMatch

CV = """
Suraj Pandey — AI Product Manager

SUMMARY
Product leader focused on AI and data platforms.

EXPERIENCE
SimplyPhi — Senior Product Manager, 2023-2026
Owned the AI roadmap and delivered a model-evaluation platform used by 40 analysts.
Ran discovery with stakeholders across engineering and compliance.

Pixis — Product Manager, 2021-2023
Built reporting pipelines in SQL and Python.

SKILLS
Python, SQL, roadmapping, stakeholder management, Agile

EDUCATION
MSc Business Analytics, University of Leeds
"""


def match(requirement: str, level: MatchLevel, evidence: str = "", **kw) -> RequirementMatch:  # type: ignore[no-untyped-def]
    return RequirementMatch(requirement=requirement, level=level, evidence=evidence, **kw)


class TestEvidenceVerification:
    """The guard that makes the whole report trustworthy."""

    def test_a_quote_that_is_in_the_cv_survives_and_is_attributed(self) -> None:
        index = build_index(CV)
        verified, rejected = verify_matches(index, [
            match("AI roadmap ownership", MatchLevel.STRONG, "Owned the AI roadmap"),
        ])

        assert rejected == 0
        assert verified[0].level is MatchLevel.STRONG
        assert verified[0].source is EvidenceSource.EXPERIENCE

    def test_a_fabricated_quote_is_demoted_to_missing_and_its_evidence_stripped(self) -> None:
        """A model asked for evidence sometimes produces a fluent paraphrase. Presenting that
        as a quotation would be inventing the operator's CV back at them."""
        index = build_index(CV)
        verified, rejected = verify_matches(index, [
            match("AWS", MatchLevel.EXCELLENT, "Five years of hands-on AWS architecture"),
        ])

        assert rejected == 1
        assert verified[0].level is MatchLevel.MISSING
        assert verified[0].evidence == ""
        assert verified[0].source is None

    def test_the_requirement_is_kept_even_when_its_claim_is_rejected(self) -> None:
        """Dropping it would quietly shrink the gap list — the requirement still belongs in
        the report, as a gap."""
        index = build_index(CV)
        verified, _ = verify_matches(index, [
            match("Kubernetes", MatchLevel.STRONG, "Ran production Kubernetes clusters"),
        ])
        assert [m.requirement for m in verified] == ["Kubernetes"]

    def test_a_paraphrase_close_to_the_original_is_still_rejected(self) -> None:
        """"Owned the AI roadmap" is in the CV; "Owned AI roadmaps" is not. Near-misses are
        exactly where a plausible fabrication hides."""
        index = build_index(CV)
        _, rejected = verify_matches(index, [
            match("roadmap", MatchLevel.STRONG, "Owned AI roadmaps and strategy"),
        ])
        assert rejected == 1

    def test_whitespace_and_case_differences_do_not_reject_a_real_quote(self) -> None:
        """Verification must not be so brittle that real evidence is thrown away."""
        index = build_index(CV)
        _, rejected = verify_matches(index, [
            match("SQL", MatchLevel.STRONG, "built   REPORTING pipelines in sql"),
        ])
        assert rejected == 0

    def test_an_already_missing_match_is_left_alone(self) -> None:
        index = build_index(CV)
        verified, rejected = verify_matches(index, [match("Rust", MatchLevel.MISSING)])
        assert rejected == 0
        assert verified[0].level is MatchLevel.MISSING


class TestAttribution:
    def test_evidence_is_traced_to_the_right_cv_section(self) -> None:
        index = build_index(CV)
        source, _ = attribute(index, "MSc Business Analytics")
        assert source is EvidenceSource.EDUCATION

    def test_the_employer_is_the_nearest_preceding_one_not_the_first_in_the_cv(self) -> None:
        """Attributing every match to whichever employer appears first would be worse than
        no attribution — it would be confidently wrong."""
        index = build_index(CV)
        _, employer = attribute(index, "Built reporting pipelines in SQL")
        assert "Pixis" in employer

    def test_a_quote_that_is_absent_reports_no_source_at_all(self) -> None:
        index = build_index(CV)
        source, employer = attribute(build_index(CV), "Kubernetes operator development")
        assert source is None
        assert employer == ""
        assert index is not None


class TestCategoryScoring:
    def test_required_gaps_cost_more_than_preferred_gaps(self) -> None:
        """A CV meeting every must-have and missing two nice-to-haves must not score the same
        as the reverse."""
        meets_required = [
            match("A", MatchLevel.STRONG, required=True),
            match("B", MatchLevel.MISSING, required=False),
            match("C", MatchLevel.MISSING, required=False),
        ]
        misses_required = [
            match("A", MatchLevel.MISSING, required=True),
            match("B", MatchLevel.STRONG, required=False),
            match("C", MatchLevel.STRONG, required=False),
        ]
        good, _ = score_categories(meets_required, job_facts={})
        bad, _ = score_categories(misses_required, job_facts={})
        assert overall_score(good) > overall_score(bad)

    def test_a_category_is_not_scored_when_the_posting_says_nothing_about_it(self) -> None:
        """A "salary fit: 90%" against a posting with no band is a number invented out of
        nothing, and it looks exactly like a measured one."""
        _, not_assessed = score_categories([match("A", MatchLevel.STRONG)], job_facts={})
        assert any("Salary" in reason for reason in not_assessed)
        assert any("publishes no band" in reason for reason in not_assessed)

    def test_salary_is_scored_only_when_both_sides_are_known(self) -> None:
        categories, not_assessed = score_categories(
            [match("A", MatchLevel.STRONG)],
            job_facts={"salary_max_k": 95},
        )
        assert not any(c.key == "salary" for c in categories)
        assert any("no expectation" in reason for reason in not_assessed)

        categories, _ = score_categories(
            [match("A", MatchLevel.STRONG)],
            job_facts={"salary_max_k": 95, "salary_expectation_k": 80},
        )
        assert next(c for c in categories if c.key == "salary").score == 1.0

    def test_seniority_needs_both_the_posting_and_the_cv(self) -> None:
        _, not_assessed = score_categories([match("A", MatchLevel.STRONG)], job_facts={})
        assert any("Seniority" in reason for reason in not_assessed)

        categories, _ = score_categories(
            [match("A", MatchLevel.STRONG)],
            job_facts={"seniority": "senior", "cv_seniority": "senior"},
        )
        assert next(c for c in categories if c.key == "seniority").score == 1.0

    def test_every_category_states_how_it_was_computed(self) -> None:
        """"Where did this number come from" has to be answerable on the page."""
        categories, _ = score_categories(
            [match("A", MatchLevel.STRONG, required=True)], job_facts={}
        )
        assert all(c.method for c in categories)

    def test_the_overall_ignores_unassessed_dimensions(self) -> None:
        """Counting an unknown as zero, or as a neutral half, lets the absence of information
        move a score that is supposed to reflect evidence."""
        categories, _ = score_categories(
            [match("A", MatchLevel.EXCELLENT, required=True)], job_facts={}
        )
        assert overall_score(categories) == 1.0

    def test_no_categories_at_all_scores_zero_rather_than_raising(self) -> None:
        assert overall_score([]) == 0.0

    def test_level_weights_separate_strong_from_excellent(self) -> None:
        assert LEVEL_WEIGHT[MatchLevel.EXCELLENT] > LEVEL_WEIGHT[MatchLevel.STRONG]
        assert LEVEL_WEIGHT[MatchLevel.MISSING] == 0.0


class TestRecommendations:
    def test_a_missing_requirement_is_never_dressed_up_as_something_to_claim(self) -> None:
        """The single most dangerous output this product could produce."""
        recs = build_recommendations([match("AWS", MatchLevel.MISSING)])

        assert recs[0].kind == "cannot_evidence"
        assert recs[0].grounded_in == ""
        assert "not evidenced" in recs[0].text
        assert "if not, this is a genuine gap" in recs[0].text

    def test_a_weak_match_is_strengthened_using_the_operators_own_words(self) -> None:
        recs = build_recommendations([
            match("SQL", MatchLevel.WEAK, "Built reporting pipelines in SQL"),
        ])
        assert recs[0].kind == "strengthen"
        assert "Built reporting pipelines in SQL" in recs[0].grounded_in

    def test_quantification_is_suggested_only_where_numbers_are_absent(self) -> None:
        with_numbers = build_recommendations([
            match("Delivery", MatchLevel.STRONG, "delivered a platform used by 40 analysts"),
        ])
        without = build_recommendations([
            match("Delivery", MatchLevel.STRONG, "delivered a model-evaluation platform"),
        ])
        assert not any(r.kind == "quantify" for r in with_numbers)
        assert any(r.kind == "quantify" for r in without)

    def test_every_non_gap_recommendation_is_grounded_in_real_cv_text(self) -> None:
        recs = build_recommendations([
            match("SQL", MatchLevel.PARTIAL, "pipelines in SQL"),
            match("Rust", MatchLevel.MISSING),
        ])
        for rec in recs:
            if rec.kind != "cannot_evidence":
                assert rec.grounded_in, f"{rec.kind} recommendation invented from nothing"


class TestKeywordFallback:
    """The route taken when no LLM is available — weaker, and labelled as such by the caller."""

    def test_a_skill_in_both_the_posting_and_the_cv_is_matched_with_a_real_quote(self) -> None:
        matches = keyword_requirements(
            description="We need strong Python and SQL experience.",
            tagged_skills=[],
            cv_text=CV,
        )
        by_requirement = {m.requirement.casefold(): m for m in matches}
        python = by_requirement.get("python")
        assert python is not None
        assert python.level is MatchLevel.STRONG
        assert "Python" in python.evidence

    def test_a_skill_absent_from_the_cv_is_reported_missing_with_no_evidence(self) -> None:
        matches = keyword_requirements(
            description="Kubernetes administration is essential.",
            tagged_skills=["kubernetes"],
            cv_text=CV,
        )
        kubernetes = next(m for m in matches if "kubernetes" in m.requirement.casefold())
        assert kubernetes.level is MatchLevel.MISSING
        assert kubernetes.evidence == ""

    def test_the_postings_own_wording_is_preferred_over_a_bare_vocabulary_term(self) -> None:
        matches = keyword_requirements(
            description="Requirements:\n- Proven experience with Python at scale\n",
            tagged_skills=["python"],
            cv_text=CV,
        )
        python = next(m for m in matches if "python" in m.requirement.casefold())
        assert "Proven experience" in python.requirement

    def test_tagged_skills_are_not_duplicated_by_the_vocabulary_pass(self) -> None:
        matches = keyword_requirements(
            description="Python, python, PYTHON", tagged_skills=["Python"], cv_text=CV
        )
        assert sum(1 for m in matches if "python" in m.requirement.casefold()) == 1

    @pytest.mark.parametrize("cv", ["", None])
    def test_an_empty_cv_yields_gaps_rather_than_raising(self, cv) -> None:  # type: ignore[no-untyped-def]
        matches = keyword_requirements(
            description="Python required", tagged_skills=["python"], cv_text=cv
        )
        assert all(m.level is MatchLevel.MISSING for m in matches)
