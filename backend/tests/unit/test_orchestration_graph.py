"""Unit tests for core.orchestration.graph — the real LangGraph Eligibility->Scoring pipeline.

Exercises the compiled graph end-to-end against a real Job row (sponsor fields actually
persisted) with the two node dependencies mocked out, plus the top-level entry point's
best-effort failure containment.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.core.orchestration import graph as graph_module
from app.models.agent_run import AgentRun
from app.models.enums import AgentName, SponsorConfidence
from app.models.job import Job
from app.schemas.resume_recommendation import ResumeRecommendation
from tests.conftest import TEST_USER_ID


def _uid(prefix: str) -> str:
    return prefix.ljust(30, "0") + "aa"


async def _make_job(db_session) -> Job:
    job = Job(
        id=_uid("job"),
        user_id=TEST_USER_ID,
        platform="remotive",
        platform_job_id="ext-1",
        title="Data Scientist",
        company="Acme Sponsors Ltd",
        url="https://example.com/job",
        description="We offer visa sponsorship for this role.",
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


class TestRunPostEnrichmentPipeline:
    async def test_eligibility_then_scoring_both_run_and_record(self, db_session) -> None:
        job = await _make_job(db_session)

        fake_recommendation = ResumeRecommendation(
            job_id=job.id, recommended_resume_id=None, rankings=[], synopsis="No résumés yet.",
        )
        with patch.object(
            graph_module, "classify_sponsor",
            return_value=(SponsorConfidence.KEYWORD_DETECTED, 'Posting states: "sponsorship"'),
        ), patch.object(
            graph_module, "recommend_best_resume", new=AsyncMock(return_value=fake_recommendation),
        ):
            await graph_module.run_post_enrichment_pipeline(db_session, TEST_USER_ID, job)

        await db_session.refresh(job)
        assert job.sponsor_confidence == SponsorConfidence.KEYWORD_DETECTED
        assert job.sponsor_evidence == 'Posting states: "sponsorship"'

        runs = (
            (await db_session.execute(select(AgentRun).order_by(AgentRun.started_at)))
            .scalars()
            .all()
        )
        assert [r.agent_name for r in runs] == [AgentName.ELIGIBILITY, AgentName.SCORING]
        assert all(r.finished_at is not None for r in runs)
        assert all(r.linked_entity_type == "job" and r.linked_entity_id == job.id for r in runs)

    async def test_pipeline_failure_is_contained_best_effort(self, db_session) -> None:
        job = await _make_job(db_session)

        with patch.object(
            graph_module, "classify_sponsor", side_effect=RuntimeError("classifier exploded"),
        ):
            await graph_module.run_post_enrichment_pipeline(db_session, TEST_USER_ID, job)
            # Must not raise — a broken agent must never turn a successful enrichment
            # request into a failed one.
