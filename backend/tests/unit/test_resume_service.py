"""Unit tests for the resume service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.exceptions import RecordNotFoundError
from app.models.job import Job
from app.models.resume import Resume
from app.models.user_settings import UserSettings
from app.schemas.resume import ResumeGenerateRequest, ResumeScoreRequest
from app.services import resume as resume_service
from tests.conftest import TEST_USER_ID


async def _create_base_resume(db_session, name="Base Resume"):
    """Helper to create a base resume record."""
    r = Resume(user_id=TEST_USER_ID, name=name, type="base", template_id="modern")
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


async def _create_job(db_session, sample_job_data, suffix="0"):
    data = {**sample_job_data, "platform_job_id": f"job-{suffix}"}
    job = Job(**data)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


class TestListResumes:
    async def test_list_resumes_empty(self, db_session):
        result = await resume_service.list_resumes(db_session)
        assert result.items == []
        assert result.total == 0


class TestGenerateTailoredResume:
    async def test_generate_tailored_resume(self, db_session, sample_job_data):
        base = await _create_base_resume(db_session)
        job = await _create_job(db_session, sample_job_data)

        request = ResumeGenerateRequest(
            base_resume_id=base.id,
            job_id=job.id,
            template_id="classic",
        )
        result = await resume_service.generate_tailored_resume(db_session, request, TEST_USER_ID)

        assert result.type == "tailored"
        assert result.base_resume_id == base.id
        assert result.job_id == job.id
        assert result.template_id == "classic"
        assert "Tailored" in result.name


class TestScoreResume:
    async def test_score_resume_empty_text(self, db_session, sample_job_data):
        """Resume with no content_text returns zero scores."""
        base = await _create_base_resume(db_session)
        job = await _create_job(db_session, sample_job_data)

        request = ResumeScoreRequest(job_id=job.id)
        result = await resume_service.score_resume(db_session, base.id, request)

        assert result.resume_id == base.id
        assert result.job_id == job.id
        assert result.overall_score == 0.0
        assert result.skill_score == 0.0
        assert len(result.missing_skills) > 0
        assert len(result.suggestions) > 0

    async def test_score_resume_with_content(self, db_session, sample_job_data):
        """Resume with content_text returns real scores."""
        r = Resume(
            user_id=TEST_USER_ID,
            name="Parsed Resume",
            type="base",
            template_id="modern",
            content_text="Experienced Python developer with FastAPI and PostgreSQL skills",
        )
        db_session.add(r)
        await db_session.commit()
        await db_session.refresh(r)

        job = await _create_job(db_session, sample_job_data)

        request = ResumeScoreRequest(job_id=job.id)
        result = await resume_service.score_resume(db_session, r.id, request)

        assert result.resume_id == r.id
        assert result.job_id == job.id
        # Should have a non-zero score since resume text mentions job skills
        assert 0.0 <= result.overall_score <= 1.0
        assert 0.0 <= result.skill_score <= 1.0
        assert 0.0 <= result.keyword_score <= 1.0

    async def test_experience_score_uses_the_real_candidate_profile(
        self, db_session, sample_job_data
    ) -> None:
        """Root-cause regression: experience_score/education_score used to be computed
        against permanently-empty lists no matter what — a flat 0.0 (experience) and an
        arbitrary constant (education) on every résumé, for every job. They must now reflect
        the operator's own stored work history and education (Settings > Candidate profile)."""
        r = Resume(
            user_id=TEST_USER_ID, name="Real Resume", type="base", template_id="modern",
            content_text="Experienced Python developer with FastAPI and PostgreSQL skills",
        )
        db_session.add(r)
        db_session.add(UserSettings(
            user_id=TEST_USER_ID,
            candidate_profile={
                "experience": [
                    {
                        "title": "Senior Software Engineer", "company": "Acme",
                        "start_date": "2016", "end_date": "2024",
                        "description": "Architected systems and led delivery.",
                        "responsibilities": ["architect", "deliver"],
                    },
                ],
                "education": [{"degree": "Master's", "institution": "Some University"}],
            },
        ))
        await db_session.commit()
        await db_session.refresh(r)

        job = await _create_job(db_session, sample_job_data)
        result = await resume_service.score_resume(
            db_session, r.id, ResumeScoreRequest(job_id=job.id)
        )

        # 8 years of senior-level experience is a real, non-neutral signal — not the old
        # hard-coded 0.0 every résumé got regardless of the candidate's actual background.
        assert result.experience_score > 0.5

    async def test_experience_score_is_neutral_without_a_stored_profile(
        self, db_session, sample_job_data
    ) -> None:
        """No UserSettings row at all (never onboarded) must not crash scoring, and must
        land on the honest neutral default rather than a punishing zero."""
        r = Resume(
            user_id=TEST_USER_ID, name="No Profile Resume", type="base", template_id="modern",
            content_text="Experienced Python developer with FastAPI and PostgreSQL skills",
        )
        db_session.add(r)
        await db_session.commit()
        await db_session.refresh(r)

        job = await _create_job(db_session, sample_job_data)
        result = await resume_service.score_resume(
            db_session, r.id, ResumeScoreRequest(job_id=job.id)
        )

        assert result.experience_score == 0.5


class TestUploadResume:
    async def test_upload_resume_creates_record(self, db_session, tmp_path):
        mock_file = MagicMock()
        mock_file.filename = "my_resume.pdf"
        mock_file.read = AsyncMock(return_value=b"fake pdf content here with enough words to count")

        with patch.object(resume_service, "UPLOAD_DIR", tmp_path):
            result = await resume_service.upload_resume(db_session, mock_file, TEST_USER_ID)

        assert result.name == "my_resume.pdf"
        assert result.file_format == "pdf"
        assert result.word_count > 0
        assert result.id is not None

    async def test_upload_docx_sets_correct_format(self, db_session, tmp_path):
        mock_file = MagicMock()
        mock_file.filename = "resume.docx"
        mock_file.read = AsyncMock(return_value=b"fake docx content")

        with patch.object(resume_service, "UPLOAD_DIR", tmp_path):
            result = await resume_service.upload_resume(db_session, mock_file, TEST_USER_ID)

        assert result.file_format == "docx"

    async def test_upload_does_not_truncate_long_resume_text(self, db_session, tmp_path):
        """content_text used to be hard-capped at 5000 chars, silently dropping anything
        past ~1.5 pages of a real CV from every subsequent score/tailor operation."""
        long_text = "Experienced engineer. " * 400  # well over 5000 chars
        mock_file = MagicMock()
        mock_file.filename = "long_resume.pdf"
        mock_file.read = AsyncMock(return_value=long_text.encode())

        with patch.object(resume_service, "UPLOAD_DIR", tmp_path):
            await resume_service.upload_resume(db_session, mock_file, TEST_USER_ID)

        stored = (
            await db_session.execute(resume_service.select(Resume))
        ).scalars().one()
        assert len(stored.content_text) > 5000
        assert stored.content_text == long_text

    async def test_upload_with_no_filename(self, db_session, tmp_path):
        mock_file = MagicMock()
        mock_file.filename = None
        mock_file.read = AsyncMock(return_value=b"content")

        with patch.object(resume_service, "UPLOAD_DIR", tmp_path):
            result = await resume_service.upload_resume(db_session, mock_file, TEST_USER_ID)

        assert result.name == "Untitled Resume"
        assert result.file_format == "pdf"


class TestGetResumeNotFound:
    async def test_get_resume_not_found(self, db_session):
        with pytest.raises(RecordNotFoundError):
            await resume_service.get_resume(db_session, "nonexistent_id")


class TestExtractCandidateProfileFromResume:
    """The ATS score's experience/education factors need real structured data — this is what
    turns an already-uploaded résumé into that data instead of a hand-typed Settings form."""

    def _fake_llm(self, extracted):
        client = AsyncMock()
        client.complete_with_structured_output = AsyncMock(return_value=extracted)
        return client

    async def test_populates_an_empty_profile(self, db_session):
        from app.schemas.resume import ExtractedProfileData
        from app.schemas.settings import EducationSchema, WorkExperienceSchema

        r = Resume(
            user_id=TEST_USER_ID, name="CV", type="base", template_id="modern",
            content_text="Senior Engineer at Acme, 2020-Present. BSc Computer Science, MIT.",
        )
        db_session.add(r)
        await db_session.commit()
        await db_session.refresh(r)

        extracted = ExtractedProfileData(
            experience=[WorkExperienceSchema(
                title="Senior Engineer", company="Acme", start_date="2020", end_date="Present",
            )],
            education=[EducationSchema(degree="BSc Computer Science", institution="MIT")],
        )
        with patch.object(
            resume_service, "build_llm_client_for_user",
            AsyncMock(return_value=self._fake_llm(extracted)),
        ):
            result = await resume_service.extract_candidate_profile_from_resume(
                db_session, r.id, TEST_USER_ID,
            )

        assert result.profile_updated is True
        assert result.experience_found == 1
        assert result.education_found == 1

        stored = (
            await db_session.execute(
                select(UserSettings).where(UserSettings.user_id == TEST_USER_ID)
            )
        ).scalar_one()
        assert stored.candidate_profile["experience"][0]["company"] == "Acme"
        assert stored.candidate_profile["education"][0]["institution"] == "MIT"

    async def test_does_not_overwrite_an_existing_profile(self, db_session):
        r = Resume(
            user_id=TEST_USER_ID, name="CV", type="base", template_id="modern",
            content_text="Some resume text.",
        )
        db_session.add(r)
        settings_row = UserSettings(
            user_id=TEST_USER_ID,
            candidate_profile={"experience": [{"title": "Existing Role", "company": "Prior Co"}]},
        )
        db_session.add(settings_row)
        await db_session.commit()
        await db_session.refresh(r)

        never_called = AsyncMock(side_effect=AssertionError("LLM should not be called"))
        with patch.object(resume_service, "build_llm_client_for_user", never_called):
            result = await resume_service.extract_candidate_profile_from_resume(
                db_session, r.id, TEST_USER_ID,
            )

        assert result.profile_updated is False
        assert result.experience_found == 1
        never_called.assert_not_called()

    async def test_empty_resume_text_is_a_no_op(self, db_session):
        r = Resume(user_id=TEST_USER_ID, name="CV", type="base", template_id="modern")
        db_session.add(r)
        await db_session.commit()
        await db_session.refresh(r)

        result = await resume_service.extract_candidate_profile_from_resume(
            db_session, r.id, TEST_USER_ID,
        )

        assert result.profile_updated is False
        assert "no parsed text" in result.detail.lower()
