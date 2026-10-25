"""In-app notifications: producers (timeline events, job search), email copy, and the API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select

from app.models.application import Application
from app.models.enums import ApplicationEventType, ApplicationStatus, ConfirmationState
from app.models.job import Job
from app.models.notification import Notification
from app.models.resume import Resume
from app.models.user import User
from app.services import notifications
from app.services.gmail_send import NotifyOutcome
from app.services.timeline import record_event
from tests.conftest import TEST_USER_ID

API = "/api/v1/notifications"
OTHER = "otheruser000000000000000000000cc"


def _job(db, **kw):  # noqa: ANN001, ANN202
    job = Job(
        id=uuid4().hex,
        user_id=TEST_USER_ID,
        platform="careers:monzo",
        platform_job_id=uuid4().hex,
        title=kw.pop("title", "Senior Product Manager"),
        company=kw.pop("company", "Monzo"),
        location="London",
        url="https://example.invalid/j",
        status="new",
        **kw,
    )
    db.add(job)
    return job


async def _app(db, job, **kw):  # noqa: ANN001, ANN202
    app = Application(
        user_id=TEST_USER_ID, job_id=job.id, apply_mode="review",
        status=kw.pop("status", ApplicationStatus.APPROVED), **kw,
    )
    db.add(app)
    await db.flush()
    return app


async def _count(db, **where) -> int:  # noqa: ANN001
    stmt = select(func.count()).select_from(Notification)
    for k, v in where.items():
        stmt = stmt.where(getattr(Notification, k) == v)
    return int(await db.scalar(stmt))


class TestNotify:
    async def test_is_idempotent_on_dedup_key(self, db_session, current_user) -> None:
        for _ in range(3):
            await notifications.notify(
                db_session, TEST_USER_ID, kind="system", title="x", dedup_key="same", email=False
            )
        await db_session.commit()
        assert await _count(db_session, dedup_key="same") == 1

    async def test_a_duplicate_never_breaks_the_callers_transaction(
        self, db_session, current_user
    ) -> None:
        job = _job(db_session)
        await notifications.notify(
            db_session, TEST_USER_ID, kind="system", title="x", dedup_key="d", email=False
        )
        await notifications.notify(
            db_session, TEST_USER_ID, kind="system", title="x", dedup_key="d", email=False
        )
        await db_session.commit()  # the job added before the duplicate is still committed
        assert await db_session.get(Job, job.id) is not None

    async def test_email_kinds_are_emailed_and_stamped(self, db_session, current_user) -> None:
        with patch(
            "app.services.gmail_send.send_notification_email",
            new=AsyncMock(return_value=NotifyOutcome.SENT),
        ) as send:
            row = await notifications.notify(
                db_session, TEST_USER_ID, kind="action_required", title="Needs you", dedup_key="a"
            )
        send.assert_awaited_once()
        assert "Needs you" in send.await_args.kwargs["subject"]
        assert row.emailed_at is not None

    async def test_gmail_not_connected_leaves_it_in_app_only(
        self, db_session, current_user
    ) -> None:
        with patch(
            "app.services.gmail_send.send_notification_email",
            new=AsyncMock(return_value=NotifyOutcome.NOT_CONNECTED),
        ):
            row = await notifications.notify(
                db_session, TEST_USER_ID, kind="best_match", title="m", dedup_key="b"
            )
        assert row is not None and row.emailed_at is None


class TestFromApplicationEvents:
    async def test_submission_notifies_without_a_second_email(
        self, db_session, current_user
    ) -> None:
        job = _job(db_session)
        app = await _app(db_session, job, confirmation_state=ConfirmationState.CONFIRMED)
        with patch(
            "app.services.gmail_send.send_notification_email", new=AsyncMock()
        ) as send:
            await record_event(
                db_session, app, ApplicationEventType.APPLICATION_SUBMITTED, "Submitted"
            )
        await db_session.commit()
        row = (await db_session.execute(select(Notification))).scalar_one()
        assert row.kind == "application_submitted"
        assert row.title == "Applied: Senior Product Manager at Monzo"
        assert row.link == f"/applications/{app.id}"
        send.assert_not_awaited()  # gmail_send.notify_application_submitted owns that email

    async def test_a_rehearsal_never_reads_as_a_submission(
        self, db_session, current_user
    ) -> None:
        job = _job(db_session)
        app = await _app(db_session, job, confirmation_state=ConfirmationState.SIMULATED)
        await record_event(db_session, app, ApplicationEventType.APPLICATION_SUBMITTED, "x")
        await db_session.commit()
        row = (await db_session.execute(select(Notification))).scalar_one()
        assert row.title.startswith("Rehearsal only (nothing sent)")
        assert row.severity == "info"

    async def test_failures_and_needs_you_are_notified_and_emailed(
        self, db_session, current_user
    ) -> None:
        job = _job(db_session)
        app = await _app(db_session, job)
        with patch(
            "app.services.gmail_send.send_notification_email",
            new=AsyncMock(return_value=NotifyOutcome.SENT),
        ) as send:
            await record_event(db_session, app, ApplicationEventType.ERROR, "Login wall")
            await record_event(
                db_session, app, ApplicationEventType.USER_ACTION_REQUIRED, "Approve it",
                payload={"action": "approve"},
            )
        await db_session.commit()
        kinds = {r.kind for r in (await db_session.execute(select(Notification))).scalars()}
        assert kinds == {"application_failed", "action_required"}
        assert send.await_count == 2

    async def test_routine_status_changes_are_not_noise(self, db_session, current_user) -> None:
        job = _job(db_session)
        app = await _app(db_session, job)
        await record_event(db_session, app, ApplicationEventType.STATUS_CHANGED, "moved")
        await record_event(db_session, app, ApplicationEventType.NOTE_ADDED, "note")
        await db_session.commit()
        assert await _count(db_session) == 0


CV = (
    "Alex Morgan, London. Product manager with six years shipping B2B data products. Owned the "
    "roadmap and prioritisation for an analytics platform, working with engineering, design and "
    "sales. KEY SKILLS Roadmap, Prioritisation, Stakeholder management, SQL, Agile, metrics, "
    "discovery, PRDs, A/B testing, experimentation. WORK EXPERIENCE "
    "• Led discovery with 30 customers and cut time-to-value by 40%. "
    "• Defined OKRs and metrics for the analytics dashboard, reviewed weekly with leadership."
)
POSTING = (
    "Requirements: strong SQL, stakeholder management, prioritisation, product roadmap, "
    "defining metrics, discovery and A/B testing experience. You will write PRDs and work in an "
    "agile team with engineering and design to deliver the roadmap. " * 2
)


class TestNewJobs:
    async def _search(self, db_session, listings):  # noqa: ANN001, ANN202
        from app.schemas.job import JobSearchRequest
        from app.services import job_search

        platform = AsyncMock()
        platform.search = AsyncMock(return_value=listings)
        with (
            patch.object(job_search.platform_registry, "has", return_value=True),
            patch.object(job_search.platform_registry, "create", return_value=platform),
            patch("app.services.gmail_send.send_notification_email", new=AsyncMock()),
        ):
            return await job_search.search_jobs(
                db_session, JobSearchRequest(query="pm", platforms=["reed"]), TEST_USER_ID
            )

    def _listing(self, n, desc=POSTING, location="London, England, United Kingdom"):  # noqa: ANN001, ANN202
        from app.core.automation.platforms.base import JobListing

        return JobListing(
            platform="reed", platform_job_id=f"r{n}", title=f"Product Manager {n}",
            company=f"Co{n}", location=location, url=f"https://example.invalid/{n}",
            description=desc,
        )

    async def test_new_uk_jobs_and_strong_matches_are_announced(
        self, db_session, current_user
    ) -> None:
        db_session.add(
            Resume(user_id=TEST_USER_ID, name="cv", type="base", template_id="m", content_text=CV)
        )
        await db_session.commit()
        await self._search(db_session, [self._listing(1), self._listing(2, desc="Thin.")])
        rows = (await db_session.execute(select(Notification))).scalars().all()
        kinds = [r.kind for r in rows]
        assert kinds.count("new_jobs") == 1
        assert "2 new UK jobs found" in next(r.title for r in rows if r.kind == "new_jobs")
        best = [r for r in rows if r.kind == "best_match"]
        assert len(best) == 1  # the thin posting is never scored as a "strong match"
        assert best[0].link.startswith("/resume-checker?job=")

    async def test_jobs_seen_again_are_not_new(self, db_session, current_user) -> None:
        await self._search(db_session, [self._listing(1)])
        before = await _count(db_session, kind="new_jobs")
        await self._search(db_session, [self._listing(1)])
        assert await _count(db_session, kind="new_jobs") == before

    async def test_no_resume_means_no_best_match_claims(self, db_session, current_user) -> None:
        await self._search(db_session, [self._listing(3)])
        assert await _count(db_session, kind="best_match") == 0


class TestApi:
    async def _seed(self, db_session) -> None:  # noqa: ANN001
        db_session.add(User(id=OTHER, email="other@example.com", hashed_password="x"))
        for i, uid in enumerate([TEST_USER_ID, TEST_USER_ID, OTHER]):
            db_session.add(
                Notification(user_id=uid, kind="system", title=f"n{i}", dedup_key=f"k{i}")
            )
        await db_session.commit()

    async def test_feed_is_tenant_scoped_with_unread_count(
        self, client, db_session, current_user
    ) -> None:
        await self._seed(db_session)
        body = (await client.get(f"{API}/")).json()
        assert {i["title"] for i in body["items"]} == {"n0", "n1"}
        assert body["unread"] == 2

    async def test_mark_one_and_all_read(self, client, db_session, current_user) -> None:
        await self._seed(db_session)
        first = (await client.get(f"{API}/")).json()["items"][0]["id"]
        assert (await client.post(f"{API}/{first}/read")).json() == {"updated": 1}
        assert (await client.get(f"{API}/unread-count")).json() == {"updated": 1}
        assert (await client.post(f"{API}/read-all")).json() == {"updated": 1}
        assert (await client.get(f"{API}/unread-count")).json() == {"updated": 0}

    async def test_cannot_mark_another_users_notification(
        self, client, db_session, current_user
    ) -> None:
        from app.db.tenant import current_user_id

        await self._seed(db_session)
        token = current_user_id.set(None)  # read the other tenant's row id unscoped
        try:
            theirs = (
                await db_session.execute(
                    select(Notification.id).where(Notification.user_id == OTHER)
                )
            ).scalar_one()
        finally:
            current_user_id.reset(token)
        assert (await client.post(f"{API}/{theirs}/read")).json() == {"updated": 0}

    async def test_requires_authentication(self, anon_client) -> None:
        assert (await anon_client.get(f"{API}/")).status_code == 401
