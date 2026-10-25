"""Core rules of the résumé checker: parsing, targets, the experience-policy guard, LLM validation."""

from __future__ import annotations

from app.core.resume_check.review import LlmReview, build_prompt, validate_review
from app.core.resume_check.suggest import evidence_status
from app.core.resume_check.targets import job_target, roles_target
from app.core.resume_check.text import (
    contains_verbatim,
    find_evidence,
    has_symbol_font_bullets,
    split_blocks,
)
from app.core.skills.catalog import SKILLS

WRAPPED = """Jo Bloggs
KEY SKILLS
Python, SQL, Stakeholder management
WORK & LEADERSHIP EXPERIENCE
SimplyPhi, Woking, UK, (Technology Team)
 Built a retrieval pipeline over 400K records using embeddings and PostgreSQL that
cut analyst search time by 35% across three teams.
 Responsible for the weekly stakeholder report.
EDUCATION
BSc Mathematics, 2015
"""


class TestText:
    def test_wrapped_bullets_are_rejoined_into_one_block(self) -> None:
        blocks = split_blocks(WRAPPED)
        exp = [b for b in blocks if b.section == "experience" and b.is_bullet]
        assert len(exp) == 2
        assert exp[0].text.startswith("Built a retrieval pipeline")
        assert exp[0].text.endswith("across three teams.")

    def test_an_employer_line_is_not_mistaken_for_a_skills_heading(self) -> None:
        # Regression: "(Technology Team)" matched the skills rule and swallowed the history.
        blocks = split_blocks(WRAPPED)
        assert any(b.section == "experience" for b in blocks)
        assert not any("retrieval" in b.text for b in blocks if b.section == "skills")

    def test_symbol_font_bullets_are_detected(self) -> None:
        assert has_symbol_font_bullets(WRAPPED)
        assert not has_symbol_font_bullets("• normal bullet")

    def test_evidence_is_verbatim_and_prefers_experience(self) -> None:
        blocks = split_blocks(WRAPPED)
        quotes = find_evidence(SKILLS["sql"], blocks)
        assert quotes[0][1] == "experience" or quotes[0][1] == "skills"
        for quote, _ in quotes:
            assert contains_verbatim(WRAPPED, quote.strip("…"))

    def test_contains_verbatim_ignores_wrapping_and_case(self) -> None:
        assert contains_verbatim(WRAPPED, "built a retrieval pipeline over 400K records using")
        assert not contains_verbatim(WRAPPED, "Built a retrieval pipeline at Google")


class TestTargets:
    def test_requirements_vs_nice_to_have_headings(self) -> None:
        posting = (
            "About the role\nYou'll shape our platform.\n"
            "Requirements:\nStrong SQL.\nStakeholder management across functions.\n"
            "Product roadmap ownership.\nPrioritisation under ambiguity.\nDefining metrics.\n"
            "Nice to have:\nA/B testing.\n"
        )
        t = {s.skill.key: s.must_have for s in job_target("Product Manager", posting).skills}
        assert t["sql"] is True
        assert t["experimentation"] is False

    def test_a_thin_posting_is_topped_up_from_the_role_profile(self) -> None:
        target = job_target("Product Manager", "Join us. SQL helpful.")
        assert target.used_role_profile is True
        assert len(target.skills) >= 6

    def test_a_posting_with_no_must_haves_does_not_make_everything_optional(self) -> None:
        posting = "\n".join(
            ["We use SQL, Python, Tableau, Jira, Figma and Agile delivery every day."] * 2
        )
        target = job_target("Data Analyst", posting)
        assert any(s.must_have for s in target.skills)

    def test_roles_target_is_must_haves_first(self) -> None:
        skills = roles_target(["AI Product Manager"]).skills
        flags = [s.must_have for s in skills]
        assert flags == sorted(flags, reverse=True)


RESUME = "Led discovery with 30 customers. Wrote PRDs in Jira. BSc Computer Science."


def test_a_b_tests_phrasing_counts_as_experimentation() -> None:
    from app.core.skills.aggregate import _present

    assert _present(SKILLS["experimentation"], "ran a/b tests on onboarding")
    assert _present(SKILLS["experimentation"], "designed an a/b test")


class TestEvidencePolicy:
    def test_a_rewrite_using_only_existing_facts_is_supported(self) -> None:
        assert evidence_status("Led discovery with 30 customers", RESUME) == "supported"

    def test_an_invented_metric_is_add_only_if_true(self) -> None:
        assert evidence_status("Led discovery with 30 customers, +25% NPS", RESUME) == (
            "add_only_if_true"
        )

    def test_an_invented_employer_is_add_only_if_true(self) -> None:
        assert evidence_status("Led discovery at Google", RESUME) == "add_only_if_true"

    def test_an_invented_credential_is_add_only_if_true(self) -> None:
        assert evidence_status("Certified Scrum product owner", RESUME) == "add_only_if_true"

    def test_a_new_skill_is_add_only_if_true(self) -> None:
        assert evidence_status("Wrote PRDs and ran A/B tests", RESUME) == "add_only_if_true"

    def test_a_placeholder_is_add_only_if_true(self) -> None:
        assert evidence_status("Wrote PRDs that cut cycle time by [x]", RESUME) == (
            "add_only_if_true"
        )


class TestLlmValidation:
    def test_drops_unknown_sections_duplicates_and_invented_originals(self) -> None:
        review = LlmReview(
            summary="ok",
            section_notes=[
                {"section": "skills", "note": "a"},
                {"section": "skills", "note": "dup"},
                {"section": "hobbies", "note": "x"},
            ],
            rewrites=[
                {"section": "experience", "original": "Wrote PRDs in Jira.",
                 "suggested": "Wrote PRDs in Jira", "reason": "r"},
                {"section": "experience", "original": "Ran a $5M budget.",
                 "suggested": "Ran a $5M budget", "reason": "r"},
                {"section": "awards", "original": "Wrote PRDs in Jira.",
                 "suggested": "x", "reason": "r"},
            ],
        )
        notes, suggestions, rejected = validate_review(review, RESUME)
        assert [n.section for n in notes] == ["skills"]
        assert len(suggestions) == 1 and suggestions[0].evidence_status == "supported"
        assert rejected == 4

    def test_the_model_cannot_mark_its_own_invention_as_supported(self) -> None:
        review = LlmReview(
            summary="ok",
            rewrites=[{"section": "experience", "original": "Wrote PRDs in Jira.",
                       "suggested": "Wrote PRDs in Jira for 12 squads at Meta", "reason": "r"}],
        )
        _, suggestions, _ = validate_review(review, RESUME)
        assert suggestions[0].evidence_status == "add_only_if_true"


def test_prompt_states_the_policy_and_truncation() -> None:
    from app.core.resume_check.review import SYSTEM_PROMPT
    from app.schemas.resume_check import (
        AtsKeywords,
        CheckTarget,
        CorpusInfo,
        FitScore,
        ResumeCheckResponse,
    )

    check = ResumeCheckResponse(
        resume_id="r", resume_name="cv", target=CheckTarget(kind="job", title="PM"),
        score=FitScore(overall=0.5, band="gap", components=[], formula="f"),
        matched_skills=[], missing_skills=[],
        ats_keywords=AtsKeywords(coverage=0, total=0, found=[], missing=[]),
        sections=[], suggestions=[], corpus=CorpusInfo(uk_jobs_scanned=0),
    )
    assert "Never invent employers" in SYSTEM_PROMPT
    assert "truncated" in build_prompt(check, "x " * 20_000)
    assert "truncated" not in build_prompt(check, "short cv")
