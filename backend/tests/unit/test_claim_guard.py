"""Unit tests for app.core.documents.claim_guard (PHASE0_AUDIT D2)."""

from __future__ import annotations

from app.core.documents.claim_guard import check_tailored_resume_for_fabrication

ORIGINAL = {
    "skills": ["python", "docker", "kubernetes"],
    "experience": [
        {"company": "Acme Corp", "title": "Engineer"},
        {"company": "Globex", "title": "Senior Engineer"},
    ],
    "education": [
        {"institution": "State University", "degree": "BSc Computer Science"},
    ],
}


class TestNoViolations:
    def test_identical_data_has_no_violations(self) -> None:
        result = check_tailored_resume_for_fabrication(ORIGINAL, ORIGINAL)
        assert not result.has_hard_violation
        assert result.fabricated_companies == []
        assert result.fabricated_institutions == []
        assert result.unsupported_skills == []

    def test_reordered_and_reworded_content_has_no_violations(self) -> None:
        """Tailoring is allowed to reorder skills and rewrite descriptions."""
        tailored = {
            "skills": ["kubernetes", "python", "docker"],
            "experience": [
                {"company": "Acme Corp", "title": "Software Engineer II"},
                {"company": "Globex", "title": "Senior Software Engineer"},
            ],
            "education": ORIGINAL["education"],
        }
        result = check_tailored_resume_for_fabrication(ORIGINAL, tailored)
        assert not result.has_hard_violation
        assert result.unsupported_skills == []

    def test_case_and_whitespace_differences_are_not_violations(self) -> None:
        tailored = {
            "skills": ["Python", "  DOCKER  "],
            "experience": [{"company": "ACME CORP", "title": "x"}],
            "education": [],
        }
        result = check_tailored_resume_for_fabrication(ORIGINAL, tailored)
        assert not result.has_hard_violation
        assert result.unsupported_skills == []


class TestHardViolations:
    def test_fabricated_company_is_detected(self) -> None:
        tailored = {
            "skills": [],
            "experience": [{"company": "Totally Made Up Inc", "title": "CEO"}],
            "education": [],
        }
        result = check_tailored_resume_for_fabrication(ORIGINAL, tailored)
        assert result.has_hard_violation
        assert "Totally Made Up Inc" in result.fabricated_companies

    def test_fabricated_institution_is_detected(self) -> None:
        tailored = {
            "skills": [],
            "experience": [],
            "education": [{"institution": "Harvard University", "degree": "PhD"}],
        }
        result = check_tailored_resume_for_fabrication(ORIGINAL, tailored)
        assert result.has_hard_violation
        assert "Harvard University" in result.fabricated_institutions

    def test_real_company_alongside_fabricated_one_still_flags_the_fake(self) -> None:
        tailored = {
            "skills": [],
            "experience": [
                {"company": "Acme Corp", "title": "Engineer"},
                {"company": "Fake Startup Ltd", "title": "Founder"},
            ],
            "education": [],
        }
        result = check_tailored_resume_for_fabrication(ORIGINAL, tailored)
        assert result.fabricated_companies == ["Fake Startup Ltd"]


class TestSoftFlags:
    def test_unsupported_skill_is_flagged_not_blocked(self) -> None:
        tailored = {
            "skills": ["python", "quantum computing"],
            "experience": [],
            "education": [],
        }
        result = check_tailored_resume_for_fabrication(ORIGINAL, tailored)
        assert not result.has_hard_violation
        assert "quantum computing" in result.unsupported_skills

    def test_empty_tailored_data_is_not_a_violation(self) -> None:
        result = check_tailored_resume_for_fabrication(ORIGINAL, {})
        assert not result.has_hard_violation
        assert result.unsupported_skills == []
