"""Unit tests for services.resume_tailoring — market signals and job-specific tailoring.

The LLM is fully mocked (matches the pattern in test_resume_service.py's
TestReviewResumeWithLLM) — these tests never make a real network call.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models.job import Job
from app.schemas.resume_intelligence import (
    CommitTailorRequest,
    ChangeDecision,
    CreateBranchRequest,
    ResumeContent,
    TailorLLMChange,
    TailorLLMOutput,
    TailorLLMTitleAnalysis,
    TailorRequest,
)
from app.services import resume_intelligence as ri
from app.services import resume_tailoring as rt
from tests.conftest import TEST_USER_ID


def _fake_llm(output: TailorLLMOutput):
    client = AsyncMock()
    client.complete_with_structured_output = AsyncMock(return_value=output)
    return client


async def _job(db, title="AI Product Manager", required=None, preferred=None, description=""):
    j = Job(
        user_id=TEST_USER_ID, platform="linkedin", platform_job_id=f"pj-{uuid.uuid4().hex[:8]}",
        title=title, company="Acme", location="Remote", url="https://x.test/job",
        description=description,
        skills_required={"required": required or [], "preferred": preferred or []},
    )
    db.add(j)
    await db.commit()
    await db.refresh(j)
    return j


class TestMarketSignals:
    async def test_computes_real_frequency_over_matching_jobs(self, db_session):
        await _job(db_session, title="AI Product Manager", required=["Python", "LLMs"])
        await _job(db_session, title="AI Product Manager", required=["Python", "RAG"])
        await _job(db_session, title="Backend Engineer", required=["Go"])  # should not match

        branch = await ri.create_branch(
            db_session, TEST_USER_ID, CreateBranchRequest(role_name="AI Product Manager"),
        )
        from app.models.resume_intelligence import ResumeBranch
        branch_row = await db_session.get(ResumeBranch, branch.id)

        result = await rt.compute_market_signals(db_session, TEST_USER_ID, branch_row)
        assert result.matched_jobs == 2
        assert result.signals["Python"].matched_jobs == 2
        assert result.signals["Python"].frequency == 1.0
        assert result.signals["LLMs"].matched_jobs == 1
        assert "Go" not in result.signals

    async def test_caches_and_reuses_within_the_stale_window(self, db_session):
        await _job(db_session, title="Data Scientist", required=["Python"])
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="Data Scientist"))
        from app.models.resume_intelligence import ResumeBranch
        branch_row = await db_session.get(ResumeBranch, branch.id)

        await rt.compute_market_signals(db_session, TEST_USER_ID, branch_row)
        await _job(db_session, title="Data Scientist", required=["Rust"])  # added after first compute

        cached = await rt.compute_market_signals(db_session, TEST_USER_ID, branch_row)
        assert "Rust" not in cached.signals  # still the cached result, not recomputed

        forced = await rt.compute_market_signals(db_session, TEST_USER_ID, branch_row, force=True)
        assert "Rust" in forced.signals

    async def test_no_matching_jobs_returns_empty_signals_not_a_crash(self, db_session):
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="Quantum Cheese Sommelier"))
        from app.models.resume_intelligence import ResumeBranch
        branch_row = await db_session.get(ResumeBranch, branch.id)
        result = await rt.compute_market_signals(db_session, TEST_USER_ID, branch_row)
        assert result.matched_jobs == 0
        assert result.signals == {}


class TestTailorJob:
    async def test_algorithmic_matched_skills_found_without_any_llm(self, db_session):
        await ri.update_master(db_session, TEST_USER_ID, ResumeContent(skills=["Python", "FastAPI"]), "seed")
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="Backend Engineer"))
        job = await _job(db_session, title="Backend Engineer", required=["Python", "Kubernetes"])

        llm_output = TailorLLMOutput(
            contextually_satisfied={}, still_missing=["Kubernetes"], ats_alignment_pct=55.0,
            role_fit_notes="Reasonable overlap.", positioning_notes="Lead with Python depth.",
            title_analysis=TailorLLMTitleAnalysis(relationship="related"),
        )
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=_fake_llm(llm_output))):
            result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id, branch_id=branch.id))

        assert "Python" in result.matched
        assert "Kubernetes" in result.missing
        assert result.ats_alignment_pct == 55.0

    async def test_never_fabricates_when_llm_unavailable(self, db_session):
        await ri.update_master(db_session, TEST_USER_ID, ResumeContent(skills=["Python"]), "seed")
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="Backend Engineer"))
        job = await _job(db_session, title="Backend Engineer", required=["Python", "Kubernetes"])

        from app.core.exceptions import LLMProviderError

        failing = AsyncMock()
        failing.complete_with_structured_output = AsyncMock(side_effect=LLMProviderError("down"))
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=failing)):
            result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id, branch_id=branch.id))

        assert "Python" in result.matched
        assert "Kubernetes" in result.missing  # algorithmic-only gap, never invented as matched
        assert result.ats_alignment_pct is None
        assert result.proposed_changes == []

    async def test_auto_selects_the_best_matching_branch_when_none_given(self, db_session):
        await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="Data Scientist"))
        pm_branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="AI Product Manager"))
        job = await _job(db_session, title="AI Product Manager", required=[])

        llm_output = TailorLLMOutput(title_analysis=TailorLLMTitleAnalysis())
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=_fake_llm(llm_output))):
            result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id))

        assert result.branch_id == pm_branch.id

    async def test_proposed_changes_without_evidence_are_dropped(self, db_session):
        await ri.get_or_create_master(db_session, TEST_USER_ID)
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="AI PM"))
        job = await _job(db_session, title="AI PM")

        llm_output = TailorLLMOutput(
            title_analysis=TailorLLMTitleAnalysis(),
            proposed_changes=[
                TailorLLMChange(change_type="modified", section="summary", after_text="Great summary", reason="fit", evidence=""),
                TailorLLMChange(change_type="modified", section="summary", after_text="Good summary", reason="fit", evidence="Based on IRIS project"),
            ],
        )
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=_fake_llm(llm_output))):
            result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id, branch_id=branch.id))

        assert len(result.proposed_changes) == 1
        assert result.proposed_changes[0].after_text == "Good summary"

    async def test_no_branches_raises_a_clear_error(self, db_session):
        job = await _job(db_session)
        with pytest.raises(Exception):
            await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id))


class TestCommitTailor:
    async def test_accepted_changes_are_applied_rejected_are_not(self, db_session):
        await ri.get_or_create_master(db_session, TEST_USER_ID)
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="AI PM"))
        job = await _job(db_session, title="AI PM", required=["LLMs"])

        llm_output = TailorLLMOutput(
            title_analysis=TailorLLMTitleAnalysis(),
            proposed_changes=[
                TailorLLMChange(change_type="modified", section="summary", after_text="Accepted summary", reason="r", evidence="e"),
                TailorLLMChange(change_type="added", section="skills", after_text="LLMs", reason="r", evidence="e"),
            ],
        )
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=_fake_llm(llm_output))):
            tailor_result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id, branch_id=branch.id))

        summary_change = next(c for c in tailor_result.proposed_changes if c.section == "summary")
        skills_change = next(c for c in tailor_result.proposed_changes if c.section == "skills")

        commit_result = await rt.commit_tailor(
            db_session, TEST_USER_ID, tailor_result.analysis_id,
            CommitTailorRequest(decisions=[
                ChangeDecision(change_id=summary_change.id, decision="accept"),
                ChangeDecision(change_id=skills_change.id, decision="reject"),
            ], commit_message="Test commit"),
        )
        assert commit_result.accepted_count == 1
        assert commit_result.rejected_count == 1

        new_version = await ri.get_version(db_session, TEST_USER_ID, commit_result.version.id)
        assert new_version.content.summary == "Accepted summary"
        assert "LLMs" not in new_version.content.skills  # rejected, never applied

    async def test_edited_text_overrides_the_proposed_after_text(self, db_session):
        await ri.get_or_create_master(db_session, TEST_USER_ID)
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="AI PM"))
        job = await _job(db_session, title="AI PM")

        llm_output = TailorLLMOutput(
            title_analysis=TailorLLMTitleAnalysis(),
            proposed_changes=[
                TailorLLMChange(change_type="modified", section="summary", after_text="Original", reason="r", evidence="e"),
            ],
        )
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=_fake_llm(llm_output))):
            tailor_result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id, branch_id=branch.id))

        change = tailor_result.proposed_changes[0]
        commit_result = await rt.commit_tailor(
            db_session, TEST_USER_ID, tailor_result.analysis_id,
            CommitTailorRequest(decisions=[
                ChangeDecision(change_id=change.id, decision="edit", edited_after_text="My own wording"),
            ]),
        )
        new_version = await ri.get_version(db_session, TEST_USER_ID, commit_result.version.id)
        assert new_version.content.summary == "My own wording"

    async def test_commit_never_mutates_the_parent_version(self, db_session):
        await ri.get_or_create_master(db_session, TEST_USER_ID)
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="AI PM"))
        parent_before = await ri.get_branch(db_session, TEST_USER_ID, branch.id)
        job = await _job(db_session, title="AI PM")

        llm_output = TailorLLMOutput(
            title_analysis=TailorLLMTitleAnalysis(),
            proposed_changes=[
                TailorLLMChange(change_type="modified", section="summary", after_text="New", reason="r", evidence="e"),
            ],
        )
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=_fake_llm(llm_output))):
            tailor_result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id, branch_id=branch.id))
        await rt.commit_tailor(
            db_session, TEST_USER_ID, tailor_result.analysis_id,
            CommitTailorRequest(decisions=[ChangeDecision(change_id=tailor_result.proposed_changes[0].id, decision="accept")]),
        )

        parent_version = await ri.get_version(db_session, TEST_USER_ID, parent_before.current_version.id)
        assert parent_version.content.summary == ""  # untouched

    async def test_accepting_a_new_experience_bullet_never_writes_it_into_the_resume(self, db_session):
        # Regression: a real run once proposed a brand-new "experience" bullet with a
        # plausible-but-invented employer and date range ("XYZ Company (2019-2024)"). The
        # operator's single "Commit version" click accepted it by default (unset decisions
        # default to accept), and the old apply logic dumped the LLM's free text straight into
        # `additional` — landing a fabricated employer in a résumé a user could submit. A new
        # experience/projects bullet must never auto-apply, accepted or not; it stays in the
        # change log only, so the operator must add real experience by hand.
        await ri.get_or_create_master(db_session, TEST_USER_ID)
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="AI PM"))
        job = await _job(db_session, title="AI PM")

        fabricated = "Product Manager, XYZ Company (2019-2024)\n- Led cross-functional teams."
        llm_output = TailorLLMOutput(
            title_analysis=TailorLLMTitleAnalysis(),
            proposed_changes=[
                TailorLLMChange(change_type="added", section="experience", after_text=fabricated, reason="r", evidence="e"),
            ],
        )
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=_fake_llm(llm_output))):
            tailor_result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id, branch_id=branch.id))

        commit_result = await rt.commit_tailor(
            db_session, TEST_USER_ID, tailor_result.analysis_id,
            CommitTailorRequest(decisions=[
                ChangeDecision(change_id=tailor_result.proposed_changes[0].id, decision="accept"),
            ]),
        )
        assert commit_result.accepted_count == 1  # logged as accepted...

        new_version = await ri.get_version(db_session, TEST_USER_ID, commit_result.version.id)
        content = new_version.content
        assert content.experience == []  # ...but never written into the résumé
        assert fabricated not in content.additional
        assert all("XYZ Company" not in note for note in content.additional)

    async def test_a_whole_list_skills_reorder_replaces_the_list_not_appends_a_joined_string(self, db_session):
        # Regression: a "reordered" skills change carries the FULL comma-joined list in both
        # before_text and after_text (not one skill). The old single-skill apply logic treated
        # that joined string as one new skill and appended it verbatim, corrupting the skills
        # list with a garbled duplicate entry instead of reordering it.
        await ri.get_or_create_master(db_session, TEST_USER_ID)
        await ri.update_master(
            db_session, TEST_USER_ID, ResumeContent(skills=["Python", "SQL", "Agile"]), "seed",
        )
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="AI PM"))
        job = await _job(db_session, title="AI PM")

        llm_output = TailorLLMOutput(
            title_analysis=TailorLLMTitleAnalysis(),
            proposed_changes=[
                TailorLLMChange(
                    change_type="reordered", section="skills",
                    before_text="Python, SQL, Agile", after_text="Agile, Python, SQL",
                    reason="r", evidence="e",
                ),
            ],
        )
        with patch.object(rt, "build_llm_client_for_user", AsyncMock(return_value=_fake_llm(llm_output))):
            tailor_result = await rt.tailor_job(db_session, TEST_USER_ID, TailorRequest(job_id=job.id, branch_id=branch.id))

        commit_result = await rt.commit_tailor(
            db_session, TEST_USER_ID, tailor_result.analysis_id,
            CommitTailorRequest(decisions=[
                ChangeDecision(change_id=tailor_result.proposed_changes[0].id, decision="accept"),
            ]),
        )
        new_version = await ri.get_version(db_session, TEST_USER_ID, commit_result.version.id)
        assert new_version.content.skills == ["Agile", "Python", "SQL"]
