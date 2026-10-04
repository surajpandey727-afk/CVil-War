"""Unit tests for the resume service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.exceptions import GenerationError, RecordNotFoundError
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


REAL_CV = """Alex Morgan
London, UK
M: 07700 900123 | E: alex.morgan@example.com
Data Scientist and Product Manager with 4 years of experience building production ML systems.
KEY SKILLS
Python, SQL, PostgreSQL, Airflow, semantic search, embeddings
WORK EXPERIENCE
Northwind Labs, London, (Platform Team)
Data Scientist to Product Manager March 2022 - Present
Atlas - Internal Data Platform
- Built vector search across 400K customer records using embeddings and PostgreSQL.
- Defined and monitored the data pipeline architecture across analytics and backend teams.
EDUCATION
University of Leeds, MSc Data Science Sept 2020 - Sept 2021
"""


@pytest.fixture(autouse=True)
def _no_language_model(monkeypatch):
    """These tests are about the document, not the model: run with none configured.

    Without this they reach whatever gateway the developer's .env points at, so a gateway that
    is slow or down changes the result (or hangs the suite) for reasons unrelated to the code.
    """
    from unittest.mock import AsyncMock

    monkeypatch.setattr(resume_service, "build_llm_client_for_user", AsyncMock(return_value=None))


class TestGenerateTailoredResume:
    """The endpoint behind the "Generate tailored" button.

    The engine this replaced rebuilt the CV from a whitelist of 24 section headings and asked
    a model to rewrite every bullet. On a CV headed "KEY SKILLS" and "WORK EXPERIENCE" it
    kept nothing, and the document it produced named employers the candidate never had. These
    assert the opposite property: what comes out is the same CV.
    """

    async def test_a_resume_with_no_readable_content_is_refused(
        self, db_session, sample_job_data
    ):
        """Silently producing a document from nothing is how the old path invented a career."""
        base = await _create_base_resume(db_session)
        job = await _create_job(db_session, sample_job_data)

        with pytest.raises(GenerationError):
            await resume_service.generate_tailored_resume(
                db_session,
                ResumeGenerateRequest(base_resume_id=base.id, job_id=job.id),
                TEST_USER_ID,
            )

    async def test_the_tailored_resume_is_still_the_candidates_resume(
        self, db_session, sample_job_data
    ):
        base = await _create_base_resume(db_session)
        base.content_text = REAL_CV
        await db_session.commit()
        job = await _create_job(db_session, sample_job_data)

        result = await resume_service.generate_tailored_resume(
            db_session,
            ResumeGenerateRequest(base_resume_id=base.id, job_id=job.id, template_id="classic"),
            TEST_USER_ID,
        )

        assert result.type == "tailored"
        assert result.base_resume_id == base.id
        assert result.job_id == job.id

        # Runs without a model configured, so no wording changes: the point here is that the
        # career survives the round trip, which is exactly what the old path destroyed.
        stored = await db_session.get(Resume, result.id)
        text = stored.content_text or ""
        for fact in (
            "Northwind Labs", "University of Leeds", "Alex Morgan",
            "March 2022 - Present", "Sept 2020 - Sept 2021", "Atlas",
        ):
            assert fact in text, f"{fact} was lost by the tailoring pass"

    async def test_the_change_log_is_recorded_on_the_resume(
        self, db_session, sample_job_data
    ):
        """A tailored CV the operator cannot interrogate is one they have to take on trust."""
        base = await _create_base_resume(db_session)
        base.content_text = REAL_CV
        await db_session.commit()
        job = await _create_job(db_session, sample_job_data)

        result = await resume_service.generate_tailored_resume(
            db_session,
            ResumeGenerateRequest(base_resume_id=base.id, job_id=job.id),
            TEST_USER_ID,
        )

        audit = (await db_session.get(Resume, result.id)).tailoring_audit
        assert audit is not None
        assert audit["structure_preserved"] is True
        assert audit["fabrication_check"] == "PASSED"
        assert audit["preserved_ratio"] >= 0.8
        assert "original_ats_score" in audit and "final_ats_score" in audit
        assert isinstance(audit["changes"], list)

    async def test_the_stored_text_is_the_tailored_text_not_the_base(
        self, db_session, sample_job_data
    ):
        """The previous implementation wrote base.content_text onto the tailored record, so
        the saved document never reflected the tailoring at all."""
        base = await _create_base_resume(db_session)
        base.content_text = REAL_CV
        await db_session.commit()
        job = await _create_job(db_session, sample_job_data)

        result = await resume_service.generate_tailored_resume(
            db_session,
            ResumeGenerateRequest(base_resume_id=base.id, job_id=job.id),
            TEST_USER_ID,
        )
        stored = await db_session.get(Resume, result.id)
        assert stored.content_text
        assert stored.ats_score is not None
        assert stored.file_path_docx, "a tailored resume must produce a document"


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

    async def test_experience_score_comes_from_the_resumes_own_dated_roles(
        self, db_session, sample_job_data
    ) -> None:
        """The score reads the résumé that would be submitted: its dated roles and the work its
        bullets describe. A résumé that shows eight dated years of relevant, quantified work
        scores higher on experience than one that only lists skills."""
        strong = Resume(
            user_id=TEST_USER_ID, name="Dated Resume", type="base", template_id="modern",
            content_text=(
                "Asha Raman\nasha@example.com | +44 7700 900123\n\nSKILLS\nPython, FastAPI, PostgreSQL\n\n"
                "EXPERIENCE\nAcme Ltd\nSenior Software Engineer\nJanuary 2016 - March 2024\n"
                "• Built FastAPI services on PostgreSQL serving 2 million requests a day.\n"
                "• Led delivery of a Python platform used by 40 teams, cutting release time by 35%.\n"
            ),
        )
        listed = Resume(
            user_id=TEST_USER_ID, name="Skills Only", type="base", template_id="modern",
            content_text="Asha Raman\n\nSKILLS\nPython, FastAPI, PostgreSQL, Docker, AWS",
        )
        db_session.add_all([strong, listed])
        await db_session.commit()
        job = await _create_job(db_session, sample_job_data)

        strong_score = await resume_service.score_resume(db_session, strong.id, ResumeScoreRequest(job_id=job.id))
        listed_score = await resume_service.score_resume(db_session, listed.id, ResumeScoreRequest(job_id=job.id))

        assert strong_score.experience_score >= listed_score.experience_score
        assert strong_score.overall_score > listed_score.overall_score
        assert strong_score.evaluation is not None and strong_score.parsing_score is not None

    async def test_scoring_needs_no_stored_candidate_profile(
        self, db_session, sample_job_data
    ) -> None:
        """No UserSettings row at all (never onboarded) must not crash scoring."""
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

        assert 0.0 <= result.overall_score <= 1.0 and 0.0 <= result.experience_score <= 1.0


class TestTextFallbackScorer:
    """The spaCy-free path — what production actually runs (spaCy is deliberately excluded
    from the serverless bundle, see requirements.txt), not just the local-dev fallback."""

    def test_weak_bullet_suggestion_survives_the_fallback_path(self) -> None:
        result = resume_service._score_with_text_fallback(
            "r1", "j1",
            "Responsible for managing the local cloud infrastructure across three regions",
            "Looking for a cloud engineer with Python and AWS experience.",
        )
        assert any("measurable result" in s for s in result.suggestions)


class TestUploadResume:
    def test_upload_dir_default_is_not_relative_to_the_working_directory(self):
        """Every test in this class patches UPLOAD_DIR to a pytest tmp_path, which is exactly
        why the real default value going stale was invisible here: it was "data/uploads",
        relative to the process CWD. That directory sits inside the deployment bundle on
        Vercel, which is read-only — every upload 500'd in production while every test using
        the patched value stayed green. The default itself must be a real, writable, absolute
        temp location (mirrors STORAGE__LOCAL_ROOT's own /tmp default), not just the tests."""
        import tempfile

        assert resume_service.UPLOAD_DIR.is_absolute()
        assert resume_service.UPLOAD_DIR.is_relative_to(tempfile.gettempdir())

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


class TestReviewResumeWithLLM:
    """The on-demand deep review — separate from score_resume, which stays algorithmic-only
    so every passive view (recommendation ranking, floating widget, the policy gate) doesn't
    pay for an LLM call it never asked for."""

    def _fake_llm(self, review):
        client = AsyncMock()
        client.complete_with_structured_output = AsyncMock(return_value=review)
        return client

    async def _seed(self, db_session, job_data):
        r = Resume(
            user_id=TEST_USER_ID, name="CV", type="base", template_id="modern",
            content_text="Senior Engineer with Jenkins and GitHub Actions experience.",
        )
        db_session.add(r)
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(r)
        await db_session.refresh(job)
        return r, job

    async def test_returns_the_llm_review_when_available(self, db_session, sample_job_data):
        from app.schemas.resume import LLMAtsReview

        r, job = await self._seed(db_session, sample_job_data)
        review = LLMAtsReview(
            semantic_score=0.82,
            contextually_satisfied_skills=["CI/CD pipelines"],
            still_missing_skills=["Kubernetes"],
            recency_note="Most recent role is current.",
            seniority_note="Titles support the required seniority.",
            weak_bullets=[],
            verdict="Strong contextual fit despite no exact CI/CD keyword.",
        )
        with patch.object(
            resume_service, "build_llm_client_for_user",
            AsyncMock(return_value=self._fake_llm(review)),
        ):
            result = await resume_service.review_resume_with_llm(
                db_session, r.id, job.id, TEST_USER_ID,
            )

        assert result.available is True
        assert result.review is not None
        assert result.review.semantic_score == 0.82
        assert "CI/CD pipelines" in result.review.contextually_satisfied_skills

    async def test_llm_failure_reports_unavailable_not_an_exception(
        self, db_session, sample_job_data
    ):
        from app.core.exceptions import LLMProviderError

        r, job = await self._seed(db_session, sample_job_data)
        failing_client = AsyncMock()
        failing_client.complete_with_structured_output = AsyncMock(
            side_effect=LLMProviderError("gateway unreachable")
        )
        with patch.object(
            resume_service, "build_llm_client_for_user",
            AsyncMock(return_value=failing_client),
        ):
            result = await resume_service.review_resume_with_llm(
                db_session, r.id, job.id, TEST_USER_ID,
            )

        assert result.available is False
        assert result.review is None
        assert result.detail

    async def test_empty_resume_text_is_unavailable_without_calling_the_llm(
        self, db_session, sample_job_data,
    ):
        r = Resume(user_id=TEST_USER_ID, name="CV", type="base", template_id="modern")
        db_session.add(r)
        job = Job(**sample_job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(r)
        await db_session.refresh(job)

        never_called = AsyncMock(side_effect=AssertionError("LLM should not be called"))
        with patch.object(resume_service, "build_llm_client_for_user", never_called):
            result = await resume_service.review_resume_with_llm(
                db_session, r.id, job.id, TEST_USER_ID,
            )

        assert result.available is False
        never_called.assert_not_called()
