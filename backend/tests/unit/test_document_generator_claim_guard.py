"""Unit tests for DocumentGenerator._tailor_resume's fabrication handling.

Verifies the claim_guard wiring end to end at the generator layer
(PHASE0_AUDIT D2): a fabricated company/institution must not reach the
rendered document, but a rejection must not blow up the whole request
either — it should fall back to the original, factually-accurate data.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.core.documents.generator import DocumentGenerator
from app.core.llm.prompts.resume_tailor import (
    EducationEntry,
    ExperienceEntry,
    TailoredResumeData,
)

ORIGINAL_RESUME_DATA = {
    "name": "Jane Doe",
    "skills": ["python", "docker"],
    "experience": [{"company": "Acme Corp", "title": "Engineer", "duration": "", "description": ""}],
    "education": [{"institution": "State University", "degree": "BSc", "year": ""}],
    "certifications": [],
    "projects": [],
}


def _make_generator(tailored: TailoredResumeData) -> DocumentGenerator:
    fake_llm = AsyncMock()
    fake_llm.complete_with_structured_output = AsyncMock(return_value=tailored)
    return DocumentGenerator(llm_client=fake_llm)


class TestTailorResumeRejectsFabrication:
    async def test_fabricated_company_is_rejected_and_falls_back_to_original(self) -> None:
        fabricated = TailoredResumeData(
            name="Jane Doe",
            skills=["python", "docker"],
            experience=[ExperienceEntry(company="A Company That Never Existed", title="CEO")],
        )
        generator = _make_generator(fabricated)

        data, unsupported_skills, fabrication_rejected = await generator._tailor_resume(
            ORIGINAL_RESUME_DATA, "some job posting",
        )

        assert fabrication_rejected is True
        assert data == ORIGINAL_RESUME_DATA
        assert unsupported_skills == []

    async def test_fabricated_institution_is_rejected_and_falls_back_to_original(self) -> None:
        fabricated = TailoredResumeData(
            name="Jane Doe",
            education=[EducationEntry(institution="A University That Never Existed", degree="PhD")],
        )
        generator = _make_generator(fabricated)

        data, _, fabrication_rejected = await generator._tailor_resume(
            ORIGINAL_RESUME_DATA, "some job posting",
        )

        assert fabrication_rejected is True
        assert data == ORIGINAL_RESUME_DATA

    async def test_legitimate_tailoring_is_accepted(self) -> None:
        legit = TailoredResumeData(
            name="Jane Doe",
            skills=["python", "docker"],
            experience=[ExperienceEntry(company="Acme Corp", title="Software Engineer II")],
            education=[EducationEntry(institution="State University", degree="BSc")],
        )
        generator = _make_generator(legit)

        data, unsupported_skills, fabrication_rejected = await generator._tailor_resume(
            ORIGINAL_RESUME_DATA, "some job posting",
        )

        assert fabrication_rejected is False
        assert data["experience"][0]["title"] == "Software Engineer II"
        assert unsupported_skills == []

    async def test_unsupported_skill_is_flagged_but_not_rejected(self) -> None:
        legit = TailoredResumeData(
            name="Jane Doe",
            skills=["python", "docker", "a completely novel skill"],
        )
        generator = _make_generator(legit)

        data, unsupported_skills, fabrication_rejected = await generator._tailor_resume(
            ORIGINAL_RESUME_DATA, "some job posting",
        )

        assert fabrication_rejected is False
        assert "a completely novel skill" in unsupported_skills
        assert "a completely novel skill" in data["skills"]  # not blocked, just flagged

    async def test_no_llm_client_returns_original_data_unflagged(self) -> None:
        generator = DocumentGenerator(llm_client=None)
        data, unsupported_skills, fabrication_rejected = await generator._tailor_resume(
            ORIGINAL_RESUME_DATA, "some job posting",
        )
        assert data == ORIGINAL_RESUME_DATA
        assert unsupported_skills == []
        assert fabrication_rejected is False
