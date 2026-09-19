"""Unit tests for core.ats.impact_matrix — the free bullet-quality pre-check."""

from __future__ import annotations

from app.core.ats.impact_matrix import check_bullet_impact, check_bullet_impact_from_text


class TestCheckBulletImpact:
    def test_no_experience_returns_no_suggestions(self) -> None:
        assert check_bullet_impact([]) == []

    def test_weak_duty_bullet_with_no_metric_is_flagged(self) -> None:
        result = check_bullet_impact([
            {
                "title": "Engineer", "company": "Acme",
                "responsibilities": ["Responsible for managing the local cloud infrastructure"],
            },
        ])
        assert len(result) == 1
        assert "cloud infrastructure" in result[0]

    def test_bullet_with_a_metric_is_not_flagged_even_with_a_weak_opener(self) -> None:
        result = check_bullet_impact([
            {
                "title": "Engineer", "company": "Acme",
                "responsibilities": ["Responsible for cutting cloud spend by 22%"],
            },
        ])
        assert result == []

    def test_strong_bullet_is_not_flagged(self) -> None:
        result = check_bullet_impact([
            {
                "title": "Engineer", "company": "Acme",
                "responsibilities": ["Reduced deployment time from 40 minutes to 8 minutes"],
            },
        ])
        assert result == []

    def test_caps_at_three_examples(self) -> None:
        weak = "Responsible for a task with no measurable outcome whatsoever here"
        result = check_bullet_impact([
            {"title": "A", "company": "X", "responsibilities": [weak] * 6},
        ])
        assert len(result) == 1
        assert result[0].count(weak) == 3

    def test_non_dict_entries_are_skipped_not_crashed_on(self) -> None:
        assert check_bullet_impact(["not a dict", None, 42]) == []

    def test_description_text_is_split_into_bullets_too(self) -> None:
        result = check_bullet_impact([
            {
                "title": "Engineer", "company": "Acme",
                "description": "Worked on the backend systems team. Handled on-call rotations.",
            },
        ])
        assert len(result) == 1

    def test_short_fragments_are_ignored(self) -> None:
        result = check_bullet_impact([
            {"title": "Engineer", "company": "Acme", "responsibilities": ["Handled it"]},
        ])
        assert result == []


class TestCheckBulletImpactFromText:
    """The text-only variant — what production's spaCy-free fallback scorer actually calls
    (see services.resume._score_with_text_fallback: spaCy is not in the serverless bundle)."""

    def test_no_text_returns_no_suggestions(self) -> None:
        assert check_bullet_impact_from_text("") == []

    def test_weak_line_in_raw_resume_text_is_flagged(self) -> None:
        text = (
            "PROFESSIONAL EXPERIENCE\n"
            "Responsible for managing the local cloud infrastructure across three regions\n"
            "Led a team of five engineers to deliver the platform migration"
        )
        result = check_bullet_impact_from_text(text)
        assert len(result) == 1
        assert "cloud infrastructure" in result[0]

    def test_strong_resume_produces_no_suggestion(self) -> None:
        text = "Cut cloud infrastructure spend 22% by migrating to spot instances"
        assert check_bullet_impact_from_text(text) == []
