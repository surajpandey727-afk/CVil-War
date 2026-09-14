"""Cross-tenant isolation: the do_orm_execute filter scopes SELECTs per user.

Covers plan exit-criteria F2 (row isolation) and F4 (analytics aggregates/GROUP BY
are scoped too).
"""

from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.db.tenant import current_user_id
from app.models.application import Application
from app.models.job import Job
from app.models.llm_usage import LLMUsage
from app.models.user import User
from app.services import analytics
from app.services import application as app_service

USER_A = "a" * 32
USER_B = "b" * 32


async def _seed(db, uid: str, n: int) -> None:
    db.add(User(id=uid, email=f"{uid[:4]}@x.com", hashed_password="x"))
    await db.flush()
    for i in range(n):
        job = Job(
            user_id=uid, platform="linkedin", platform_job_id=f"{uid[:4]}-{i}",
            title="t", company="c", url="u",
        )
        db.add(job)
        await db.flush()
        db.add(Application(user_id=uid, job_id=job.id))
    await db.commit()


class TestRowIsolation:
    async def test_select_is_scoped_to_current_user(self, db_session):
        await _seed(db_session, USER_A, 2)
        await _seed(db_session, USER_B, 3)

        token = current_user_id.set(USER_A)
        try:
            rows = (await db_session.execute(select(Application))).scalars().all()
            assert len(rows) == 2
            assert all(r.user_id == USER_A for r in rows)
        finally:
            current_user_id.reset(token)

        token = current_user_id.set(USER_B)
        try:
            rows = (await db_session.execute(select(Application))).scalars().all()
            assert len(rows) == 3
            assert all(r.user_id == USER_B for r in rows)
        finally:
            current_user_id.reset(token)

    async def test_user_a_cannot_read_user_b_row(self, db_session):
        await _seed(db_session, USER_A, 1)
        await _seed(db_session, USER_B, 1)
        b_id = None
        token = current_user_id.set(USER_B)
        try:
            b_id = (await db_session.execute(select(Application))).scalars().one().id
        finally:
            current_user_id.reset(token)

        token = current_user_id.set(USER_A)
        try:
            found = (
                await db_session.execute(select(Application).where(Application.id == b_id))
            ).scalar_one_or_none()
            assert found is None, "tenant A leaked into tenant B's row"
        finally:
            current_user_id.reset(token)


class TestAggregateIsolation:
    async def test_dashboard_and_funnel_are_scoped(self, db_session):
        await _seed(db_session, USER_A, 2)
        await _seed(db_session, USER_B, 3)

        token = current_user_id.set(USER_A)
        try:
            stats = await analytics.get_dashboard_stats(db_session)
            assert stats.total_applications == 2
            assert stats.total_jobs_found == 2

            funnel = await analytics.get_funnel(db_session)
            assert sum(entry.count for entry in funnel) == 2
        finally:
            current_user_id.reset(token)

    async def test_list_count_query_is_scoped(self, db_session):
        # Directly targets review Issue 3: the func.count(...) count_query must be scoped.
        await _seed(db_session, USER_A, 2)
        await _seed(db_session, USER_B, 3)
        token = current_user_id.set(USER_A)
        try:
            result = await app_service.list_applications(db_session)
            assert result.total == 2, f"count_query leaked across tenants: total={result.total}"
        finally:
            current_user_id.reset(token)

    async def test_llm_usage_aggregate_is_scoped(self, db_session):
        db_session.add(User(id=USER_A, email="a2@x.com", hashed_password="x"))
        db_session.add(User(id=USER_B, email="b2@x.com", hashed_password="x"))
        db_session.add(LLMUsage(user_id=USER_A, provider="openai", model="gpt-4o",
                                purpose="resume_tailor", cost_usd=0.10, total_tokens=100))
        db_session.add(LLMUsage(user_id=USER_B, provider="openai", model="gpt-4o",
                                purpose="resume_tailor", cost_usd=0.20, total_tokens=200))
        await db_session.commit()
        token = current_user_id.set(USER_A)
        try:
            usage = await analytics.get_llm_usage(db_session)
            total_tokens = sum(u.total_tokens for u in usage)
            assert total_tokens == 100, f"llm_usage aggregate leaked: {total_tokens}"
        finally:
            current_user_id.reset(token)


class TestSessionGetBypassesTenantFilter:
    """``Session.get()``/``AsyncSession.get()`` is a column/identity-map load, not a
    SELECT — the ``do_orm_execute`` filter deliberately skips it (see
    ``app/db/tenant.py``'s module docstring). Empirically confirmed: a plain
    ``db.get(Job, job_id)`` fed an attacker-reachable path parameter returns another
    tenant's row even with ``current_user_id`` set to a different user. Every route
    that resolves a path/query/body ID with ``db.get()`` (rather than a `TenantMixin`
    FK already reached through an ownership-checked object) must instead run an
    explicit ``select(Model).where(Model.id == ..., Model.user_id == user.id)``.

    These tests hit the routes over HTTP (the ``client`` fixture authenticates as
    ``TEST_USER_ID`` from ``tests.conftest``) with a job that belongs to ``USER_B``,
    seeded directly via ``db_session`` (INSERTs are not tenant-filtered).
    """

    async def _foreign_job(self, db_session) -> Job:
        db_session.add(User(id=USER_B, email="dbget-victim@x.com", hashed_password="x"))
        job = Job(
            user_id=USER_B, platform="linkedin", platform_job_id="dbget-foreign-1",
            title="t", company="c", url="https://x",
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)
        return job

    async def test_enrich_rejects_foreign_job(self, client, db_session):
        foreign = await self._foreign_job(db_session)
        with (
            patch(
                "app.api.v1.jobs.enrich_job",
                new_callable=AsyncMock,
                side_effect=lambda db, job, force=False: job,
            ) as mock_enrich,
            patch(
                "app.api.v1.jobs.run_post_enrichment_pipeline", new_callable=AsyncMock
            ) as mock_pipeline,
        ):
            resp = await client.post(f"/api/v1/jobs/{foreign.id}/enrich")
        assert resp.status_code == 404, "enrich leaked another tenant's job"
        mock_enrich.assert_not_called()
        mock_pipeline.assert_not_called()

    async def test_apply_readiness_rejects_foreign_job(self, client, db_session):
        foreign = await self._foreign_job(db_session)
        resp = await client.get(f"/api/v1/applications/readiness/{foreign.id}")
        assert resp.status_code == 404, "apply-readiness leaked another tenant's job"
