"""Assistant consequential tools: propose never acts, confirm acts through the existing
services, and everything stays inside the current user's data."""

from __future__ import annotations

from unittest.mock import AsyncMock

from sqlalchemy import select

from app.core.assistant import tokens
from app.core.assistant.context import ToolContext
from app.core.assistant.executor import make_executor
from app.models.application import Application
from app.models.enums import AgentName, ApplicationStatus, ApplyMode
from app.models.job import Job
from app.models.user import User
from app.models.user_settings import UserSettings
from app.services import assistant as service
from tests.conftest import TEST_USER_ID

OTHER_USER = "otheruser000000000000000000000bb"


def _pool() -> AsyncMock:
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=None)
    return pool


async def _job(db, data: dict, suffix: str, **over) -> Job:
    job = Job(**{**data, "platform_job_id": f"j-{suffix}", **over})
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


def _ctx(db, pool=None) -> ToolContext:
    return ToolContext(db=db, user_id=TEST_USER_ID, pool=pool)


async def _apps(db) -> list[Application]:
    return list((await db.execute(select(Application))).scalars().all())


class TestStageApplication:
    async def test_proposal_returns_token_and_creates_nothing(self, db_session, sample_job_data):
        job = await _job(db_session, sample_job_data, "1")
        out = await make_executor(_ctx(db_session))("stage_application", {"job_id": job.id})

        assert out.ok and out.pending is not None
        assert out.pending["token"] and "pending review" in out.pending["summary"]
        assert '"needs_confirmation":true' in out.content
        assert out.pending["token"] not in out.content  # the model never sees the token
        assert await _apps(db_session) == []

    async def test_confirm_stages_pending_review(self, db_session, sample_job_data, current_user):
        job = await _job(db_session, sample_job_data, "2")
        pool = _pool()
        out = await make_executor(_ctx(db_session, pool))("stage_application", {"job_id": job.id})

        res = await service.confirm(_ctx(db_session, pool), out.pending["token"])

        assert res.ok, res.message
        apps = await _apps(db_session)
        assert len(apps) == 1
        assert apps[0].status == ApplicationStatus.PENDING_REVIEW
        assert apps[0].user_id == TEST_USER_ID
        pool.enqueue_job.assert_not_awaited()  # staged, never enqueued or submitted

    async def test_autonomous_mode_still_waits_for_review(
        self, db_session, sample_job_data, current_user
    ):
        db_session.add(UserSettings(user_id=TEST_USER_ID, apply_mode="autonomous"))
        await db_session.commit()
        job = await _job(db_session, sample_job_data, "3")
        pool = _pool()
        out = await make_executor(_ctx(db_session, pool))("stage_application", {"job_id": job.id})
        res = await service.confirm(_ctx(db_session, pool), out.pending["token"])

        assert res.ok
        (app,) = await _apps(db_session)
        # Created in review mode outright, so there is no moment it sits QUEUED for the worker.
        assert app.apply_mode == ApplyMode.REVIEW
        assert app.status == ApplicationStatus.PENDING_REVIEW
        pool.enqueue_job.assert_not_awaited()

    async def test_token_cannot_be_replayed(self, db_session, sample_job_data, current_user):
        job = await _job(db_session, sample_job_data, "4")
        out = await make_executor(_ctx(db_session))("stage_application", {"job_id": job.id})
        assert (await service.confirm(_ctx(db_session), out.pending["token"])).ok
        again = await service.confirm(_ctx(db_session), out.pending["token"])
        assert again.ok is False and "already" in again.message

    async def test_non_uk_job_refused(self, db_session, sample_job_data):
        job = await _job(
            db_session, sample_job_data, "5", location="San Francisco, CA, USA", remote=False
        )
        out = await make_executor(_ctx(db_session))("stage_application", {"job_id": job.id})
        assert out.ok is False and out.pending is None


class TestApprove:
    async def test_confirm_approves_through_bulk_approve(self, db_session, sample_job_data):
        job = await _job(db_session, sample_job_data, "6")
        app = Application(
            user_id=TEST_USER_ID,
            job_id=job.id,
            apply_mode=ApplyMode.REVIEW,
            status=ApplicationStatus.PENDING_REVIEW,
        )
        db_session.add(app)
        await db_session.commit()
        pool = _pool()
        out = await make_executor(_ctx(db_session, pool))(
            "approve_applications", {"application_ids": [app.id]}
        )
        assert out.pending is not None
        await db_session.refresh(app)
        assert app.status == ApplicationStatus.PENDING_REVIEW  # proposal changed nothing

        res = await service.confirm(_ctx(db_session, pool), out.pending["token"])
        assert res.ok and "Approved 1" in res.message
        await db_session.refresh(app)
        assert app.status == ApplicationStatus.APPROVED
        pool.enqueue_job.assert_awaited_once()  # queued for the worker — not submitted here


class TestDiscovery:
    async def test_proposal_then_confirm_records_run(
        self, db_session, current_user, monkeypatch
    ):
        db_session.add(
            UserSettings(user_id=TEST_USER_ID, role_targets=[{"title": "Product Manager"}])
        )
        await db_session.commit()
        fake = AsyncMock(return_value=4)
        monkeypatch.setattr("app.services.discovery_scheduler._discover_for_user", fake)

        out = await make_executor(_ctx(db_session))("run_discovery_now", {})
        assert out.pending is not None
        fake.assert_not_awaited()

        res = await service.confirm(_ctx(db_session), out.pending["token"])
        assert res.ok and "4 job(s)" in res.message
        fake.assert_awaited_once()
        from app.models.agent_run import AgentRun

        (run,) = (await db_session.execute(select(AgentRun))).scalars().all()
        assert run.agent_name == AgentName.DISCOVERY and run.output_summary == "4 job(s) found"

    async def test_no_role_targets_no_token(self, db_session):
        out = await make_executor(_ctx(db_session))("run_discovery_now", {})
        assert out.ok is False and out.pending is None


class TestTenantScoping:
    async def test_other_users_job_is_invisible(self, db_session, sample_job_data):
        db_session.add(User(id=OTHER_USER, email="o@example.com", hashed_password="x"))
        await db_session.commit()
        theirs = await _job(db_session, {**sample_job_data, "user_id": OTHER_USER}, "x")
        execute = make_executor(_ctx(db_session))

        assert (await execute("get_job", {"job_id": theirs.id})).ok is False
        staged = await execute("stage_application", {"job_id": theirs.id})
        assert staged.ok is False and staged.pending is None
        listed = await execute("search_stored_jobs", {})
        assert theirs.id not in listed.content

    async def test_token_for_other_user_rejected(self, db_session, sample_job_data):
        job = await _job(db_session, sample_job_data, "y")
        token = tokens.issue(OTHER_USER, "stage_application", {"job_id": job.id})
        res = await service.confirm(_ctx(db_session), token)
        assert res.ok is False
        assert await _apps(db_session) == []

    async def test_forged_params_cannot_reach_other_users_job(self, db_session, sample_job_data):
        db_session.add(User(id=OTHER_USER, email="o2@example.com", hashed_password="x"))
        await db_session.commit()
        theirs = await _job(db_session, {**sample_job_data, "user_id": OTHER_USER}, "z")
        # Even a correctly signed token naming someone else's job does nothing.
        token = tokens.issue(TEST_USER_ID, "stage_application", {"job_id": theirs.id})
        res = await service.confirm(_ctx(db_session), token)
        assert res.ok is False
        assert await _apps(db_session) == []
