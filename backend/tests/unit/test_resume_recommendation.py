"""Unit tests for services.resume_recommendation — the floating ATS widget's data source."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.models.job import Job
from app.models.resume import Resume
from app.schemas.resume import ResumeScoreResponse
from app.services import resume_recommendation
from tests.conftest import TEST_USER_ID


async def _create_job(db_session, sample_job_data) -> Job:
    job = Job(**sample_job_data)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


async def _create_resume(db_session, name: str, *, archived: bool = False) -> Resume:
    from datetime import UTC, datetime

    resume = Resume(
        user_id=TEST_USER_ID, name=name, type="base", template_id="modern",
        archived_at=datetime.now(UTC) if archived else None,
    )
    db_session.add(resume)
    await db_session.commit()
    await db_session.refresh(resume)
    return resume


def _score(overall: float, missing: list[str] | None = None, suggestions: list[str] | None = None):
    return ResumeScoreResponse(
        resume_id="x", job_id="y", overall_score=overall,
        skill_score=overall, experience_score=overall, education_score=overall,
        keyword_score=overall, missing_skills=missing or [], suggestions=suggestions or [],
    )


class TestRecommendBestResume:
    async def test_no_resumes_returns_an_honest_empty_recommendation(
        self, db_session, sample_job_data
    ) -> None:
        job = await _create_job(db_session, sample_job_data)
        result = await resume_recommendation.recommend_best_resume(db_session, job.id)
        assert result.recommended_resume_id is None
        assert result.rankings == []
        assert "No résumés" in result.synopsis

    async def test_archived_resumes_are_excluded(self, db_session, sample_job_data) -> None:
        job = await _create_job(db_session, sample_job_data)
        await _create_resume(db_session, "Archived CV", archived=True)
        active = await _create_resume(db_session, "Active CV")

        with patch.object(
            resume_recommendation.resume_service, "score_resume",
            new=AsyncMock(return_value=_score(0.8)),
        ):
            result = await resume_recommendation.recommend_best_resume(db_session, job.id)

        assert len(result.rankings) == 1
        assert result.rankings[0].resume_id == active.id

    async def test_ranks_by_score_descending(self, db_session, sample_job_data) -> None:
        job = await _create_job(db_session, sample_job_data)
        low = await _create_resume(db_session, "Generalist CV")
        high = await _create_resume(db_session, "Tailored CV")

        async def _fake_score(db, resume_id, request):
            return _score(0.4) if resume_id == low.id else _score(0.9)

        with patch.object(
            resume_recommendation.resume_service, "score_resume", new=_fake_score
        ):
            result = await resume_recommendation.recommend_best_resume(db_session, job.id)

        assert result.recommended_resume_id == high.id
        assert result.rankings[0].resume_id == high.id
        assert result.rankings[1].resume_id == low.id

    async def test_synopsis_names_the_winner_and_missing_skills(
        self, db_session, sample_job_data
    ) -> None:
        job = await _create_job(db_session, sample_job_data)
        await _create_resume(db_session, "Data Science CV")

        with patch.object(
            resume_recommendation.resume_service, "score_resume",
            new=AsyncMock(return_value=_score(0.72, missing=["Kubernetes", "Terraform"])),
        ):
            result = await resume_recommendation.recommend_best_resume(db_session, job.id)

        assert "Data Science CV" in result.synopsis
        assert "72%" in result.synopsis
        assert "Kubernetes" in result.synopsis

    async def test_synopsis_flags_a_close_call_between_top_two(
        self, db_session, sample_job_data
    ) -> None:
        job = await _create_job(db_session, sample_job_data)
        a = await _create_resume(db_session, "CV Alpha")
        await _create_resume(db_session, "CV Beta")

        async def _fake_score(db, resume_id, request):
            return _score(0.80) if resume_id == a.id else _score(0.79)

        with patch.object(
            resume_recommendation.resume_service, "score_resume", new=_fake_score
        ):
            result = await resume_recommendation.recommend_best_resume(db_session, job.id)

        assert "close call" in result.synopsis.lower()
        assert "CV Beta" in result.synopsis
