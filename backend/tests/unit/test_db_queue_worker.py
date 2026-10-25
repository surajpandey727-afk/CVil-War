"""The database-as-queue worker (D-016): the production API has no Redis or browser, so a
long-running machine picks approved/queued applications straight from the database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.tenant import current_user_id
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.user import User
from app.services import dispatch
from app.workers import db_queue
from tests.conftest import TEST_USER_ID

OTHER_USER = "otheruser000000000000000000000bb"


@pytest.fixture()
async def seeded(async_engine, monkeypatch):
    """Two users, applications in every interesting status, the worker bound to this DB."""
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "async_session_factory", factory)
    monkeypatch.setattr(session_mod, "engine", async_engine)

    token = current_user_id.set(None)
    ids: dict[str, str] = {}
    async with factory() as db:
        for uid in (TEST_USER_ID, OTHER_USER):
            db.add(User(id=uid, email=f"{uid[:6]}@example.com", hashed_password="x"))
        base = datetime.now(UTC) - timedelta(hours=1)
        for n, (owner, status) in enumerate(
            [
                (TEST_USER_ID, ApplicationStatus.APPROVED),
                (TEST_USER_ID, ApplicationStatus.QUEUED),
                (TEST_USER_ID, ApplicationStatus.PENDING_REVIEW),
                (TEST_USER_ID, ApplicationStatus.APPLIED),
                (OTHER_USER, ApplicationStatus.APPROVED),
            ]
        ):
            job = Job(
                id=uuid4().hex,
                user_id=owner,
                platform="careers:monzo",
                platform_job_id=f"q{n}",
                title="PM",
                company="Monzo",
                location="London",
                url="https://example.invalid/j",
                status="new",
            )
            app = Application(
                user_id=owner, job_id=job.id, apply_mode="review", status=status
            )
            app.updated_at = base + timedelta(minutes=n)
            db.add_all([job, app])
            await db.flush()
            ids[f"{owner[:5]}-{status.value}"] = app.id
        await db.commit()
    current_user_id.reset(token)
    return factory, ids


def _fake_pipeline(factory, final_status):  # noqa: ANN001, ANN202
    calls: list[str] = []

    async def run(ctx, application_id):  # noqa: ANN001, ANN202
        calls.append(application_id)
        async with factory() as db:
            app = await db.get(Application, application_id)
            app.status = final_status
            await db.commit()

    return run, calls


class TestClaimable:
    async def test_only_approved_and_queued_rows_oldest_first(self, seeded) -> None:
        factory, ids = seeded
        token = current_user_id.set(None)
        try:
            async with factory() as db:
                got = await db_queue.claimable_ids(db)
        finally:
            current_user_id.reset(token)
        assert got == [ids["testu-approved"], ids["testu-queued"], ids["other-approved"]]

    async def test_can_be_scoped_to_one_user(self, seeded) -> None:
        factory, ids = seeded
        token = current_user_id.set(None)
        try:
            async with factory() as db:
                got = await db_queue.claimable_ids(db, user_id=OTHER_USER)
        finally:
            current_user_id.reset(token)
        assert got == [ids["other-approved"]]


class TestRunOnce:
    async def test_dry_run_writes_nothing_and_runs_nothing(self, seeded, monkeypatch) -> None:
        factory, ids = seeded
        run, calls = _fake_pipeline(factory, ApplicationStatus.APPLIED)
        monkeypatch.setattr("app.workers.tasks.run_apply_pipeline", run)
        out = await db_queue.run_once(state=db_queue.WorkerState(), dry_run=True)
        assert calls == []
        assert {r["outcome"] for r in out} == {"would_run"}
        assert len(out) == 3

    async def test_processes_every_claimable_row_across_tenants(self, seeded, monkeypatch) -> None:
        factory, ids = seeded
        run, calls = _fake_pipeline(factory, ApplicationStatus.APPLIED)
        monkeypatch.setattr("app.workers.tasks.run_apply_pipeline", run)
        out = await db_queue.run_once(state=db_queue.WorkerState())
        assert sorted(calls) == sorted(
            [ids["testu-approved"], ids["testu-queued"], ids["other-approved"]]
        )
        assert {r["outcome"] for r in out} == {"applied"}
        # Nothing pending review or already applied was touched.
        assert ids["testu-pending_review"] not in calls
        assert ids["testu-applied"] not in calls

    async def test_a_row_left_queued_by_a_policy_hold_is_backed_off(
        self, seeded, monkeypatch
    ) -> None:
        factory, ids = seeded
        run, calls = _fake_pipeline(factory, ApplicationStatus.QUEUED)
        monkeypatch.setattr("app.workers.tasks.run_apply_pipeline", run)
        state = db_queue.WorkerState(backoff_seconds=3600)
        first = await db_queue.run_once(state=state, user_id=OTHER_USER)
        second = await db_queue.run_once(state=state, user_id=OTHER_USER)
        assert [r["outcome"] for r in first] == ["queued"]
        assert second == []  # not re-run every poll
        assert calls == [ids["other-approved"]]

    async def test_restores_the_callers_tenant(self, seeded, monkeypatch) -> None:
        factory, _ = seeded
        run, _ = _fake_pipeline(factory, ApplicationStatus.APPLIED)
        monkeypatch.setattr("app.workers.tasks.run_apply_pipeline", run)
        token = current_user_id.set("sentinel")
        try:
            await db_queue.run_once(state=db_queue.WorkerState())
            assert current_user_id.get() == "sentinel"
        finally:
            current_user_id.reset(token)


class TestLockKey:
    def test_stable_and_in_int32_range(self) -> None:
        k = db_queue._lock_key("abc")
        assert k == db_queue._lock_key("abc")
        assert -(2**31) <= k < 2**31
        assert k != db_queue._lock_key("abd")


class TestCli:
    def test_prod_without_prod_database_url_is_blocked(self, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PROD_DATABASE_URL", raising=False)
        assert db_queue.main(["--prod", "--dry-run"]) == 2
        assert "BLOCKED" in capsys.readouterr().out


class TestApiLeavesWorkForTheDbWorker:
    async def test_db_queue_dispatch_does_not_run_inline(self, monkeypatch) -> None:
        from app.config.settings import get_settings

        monkeypatch.setattr(get_settings(), "apply_dispatch", "db_queue")
        ran: list[str] = []

        async def _inline(ctx, application_id):  # noqa: ANN001, ANN202
            ran.append(application_id)

        monkeypatch.setattr("app.workers.tasks.run_apply_pipeline", _inline)
        job_id = await dispatch.enqueue_apply(None, "app-1")
        assert job_id == "db-queue:app-1"
        assert ran == []

    async def test_inline_remains_the_default(self, monkeypatch) -> None:
        from app.config.settings import get_settings

        assert get_settings().apply_dispatch == "inline"
        ran: list[str] = []

        async def _inline(ctx, application_id):  # noqa: ANN001, ANN202
            ran.append(application_id)

        monkeypatch.setattr("app.workers.tasks.run_apply_pipeline", _inline)
        await dispatch.enqueue_apply(None, "app-2")
        assert ran == ["app-2"]
