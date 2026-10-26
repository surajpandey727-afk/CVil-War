"""Phase 2/3: run_apply harness wiring — trajectory persistence, review enqueue, review task.

The browser is fully mocked (build_apply_agent returns a fake agent whose run() yields a
FakeHistory); this exercises the orchestration/observation/enqueue path without a browser.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.automation.runtime import apply as apply_mod
from app.core.harness import record
from app.models.application import Application
from app.models.harness import RunTrajectory
from app.models.job import Job
from app.models.resume import Resume
from app.models.user import User
from app.workers import tasks
from app.services.approval import mark_approved
from tests.conftest import TEST_USER_ID
from tests.unit.test_observe import FakeHistory


async def _seed_app(db, *, platform: str = "linkedin", url: str = "https://x") -> Application:
    db.add(User(id=TEST_USER_ID, email="u@x.com", hashed_password="x"))
    job = Job(
        user_id=TEST_USER_ID, platform=platform, platform_job_id="j1",
        title="t", company="c", url=url,
    )
    db.add(job)
    await db.flush()
    resume = Resume(
        user_id=TEST_USER_ID, name="r", type="base", template_id="modern",
        file_path_pdf="/tmp/r.pdf",
    )
    db.add(resume)
    await db.flush()
    app = Application(
        user_id=TEST_USER_ID, job_id=job.id, resume_id=resume.id,
        status="applying", apply_mode="autonomous",
    )
    # Approved: with no live pub/sub channel (redis=None) the per-submission confirmation can
    # only be the owner's approval. These tests exercise harness mechanics, not that gate —
    # see test_an_unapproved_run_without_a_live_channel_asks_for_approval.
    mark_approved(app)
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


class _SessionCM:
    """Async-context-manager stand-in that yields the test session (for the dedicated
    observability session opened inside _record_and_review)."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


def _mock_browser(db, history=None, *, run_side_effect=None):
    """Patch the browser-use seams so run_apply drives a fake agent, and route the
    dedicated trajectory session back to the test session so it's observable."""
    store = MagicMock()
    store.load_session_cookies = AsyncMock(return_value={"cookies": [], "origins": []})
    store.get_llm_key = AsyncMock(return_value="sk-test")
    fake_agent = MagicMock()
    if run_side_effect is not None:
        fake_agent.run = AsyncMock(side_effect=run_side_effect)
    else:
        fake_agent.run = AsyncMock(return_value=history)
    # The resume is materialized from storage to a temp path for the browser.
    storage_service = MagicMock(
        return_value=MagicMock(materialize_to_temp=AsyncMock(return_value="/tmp/resume.pdf"))
    )
    return patch.multiple(
        apply_mod,
        CredentialStore=MagicMock(return_value=store),
        build_browser_profile=MagicMock(return_value=MagicMock()),
        build_apply_llm=MagicMock(return_value=MagicMock()),
        build_apply_agent=MagicMock(return_value=fake_agent),
        StorageService=storage_service,
        async_session_factory=lambda: _SessionCM(db),
    )


class _RaisingStructured(FakeHistory):
    """A history whose structured_output property raises (malformed agent done-text)."""

    @property
    def structured_output(self):
        raise ValueError("agent done-text is not valid ApplicationResult JSON")


class TestRunApplyHarness:
    async def test_persists_trajectory_and_enqueues_review(self, db_session):
        app = await _seed_app(db_session)
        history = FakeHistory(actions=["go_to_url", "done"], urls=["https://x/job"])
        redis = MagicMock()
        redis.enqueue_job = AsyncMock()

        with _mock_browser(db_session, history):
            result = await apply_mod.run_apply(db_session, app, redis=redis)

        assert result.submitted is True
        trajs = (
            await db_session.execute(
                select(RunTrajectory).where(RunTrajectory.application_id == app.id)
            )
        ).scalars().all()
        assert len(trajs) == 1
        redis.enqueue_job.assert_awaited_once()
        call = redis.enqueue_job.await_args
        assert call.args[0] == "review_application_run"
        assert call.args[1] == trajs[0].id

    async def test_screenshots_reach_the_application_row_not_just_the_trajectory(
        self, db_session,
    ):
        """Pins a real gap: `Application.browser_screenshots` was a column nobody ever
        wrote to — real screenshots only ever reached `RunTrajectory.screenshots`, which
        EvidencePanel/a future lightbox would have to join out to instead of reading
        straight off the application."""
        app = await _seed_app(db_session)
        history = FakeHistory(
            actions=["go_to_url", "done"], urls=["https://x/job"],
            screenshots=["/tmp/shots/1.png", "/tmp/shots/2.png"],
        )
        with _mock_browser(db_session, history):
            await apply_mod.run_apply(db_session, app, redis=None)

        await db_session.refresh(app)
        assert app.browser_screenshots == ["/tmp/shots/1.png", "/tmp/shots/2.png"]

    async def test_no_redis_persists_trajectory_but_skips_review(self, db_session):
        app = await _seed_app(db_session)
        with _mock_browser(db_session, FakeHistory()):
            await apply_mod.run_apply(db_session, app, redis=None)
        trajs = (
            await db_session.execute(
                select(RunTrajectory).where(RunTrajectory.application_id == app.id)
            )
        ).scalars().all()
        assert len(trajs) == 1

    async def test_malformed_structured_output_does_not_abort(self, db_session):
        """A raising structured_output property must fall back, not crash + skip recording."""
        app = await _seed_app(db_session)
        with _mock_browser(db_session, _RaisingStructured(final="Submitted, confirmation #42")):
            result = await apply_mod.run_apply(db_session, app, redis=None)
        assert result.submitted is True  # fell back to final_result()
        trajs = (
            await db_session.execute(
                select(RunTrajectory).where(RunTrajectory.application_id == app.id)
            )
        ).scalars().all()
        assert len(trajs) == 1  # trajectory still persisted

    async def test_run_failure_records_failed_trajectory_and_reraises(self, db_session):
        """When agent.run raises, the harness must still record + review, then re-raise."""
        app = await _seed_app(db_session)
        redis = MagicMock()
        redis.enqueue_job = AsyncMock()

        with _mock_browser(db_session, run_side_effect=RuntimeError("CDP Connection refused")):
            with pytest.raises(RuntimeError, match="Connection refused"):
                await apply_mod.run_apply(db_session, app, redis=redis)

        trajs = (
            await db_session.execute(
                select(RunTrajectory).where(RunTrajectory.application_id == app.id)
            )
        ).scalars().all()
        assert len(trajs) == 1 and trajs[0].status == "failed"
        redis.enqueue_job.assert_awaited_once()
        signals = redis.enqueue_job.await_args.args[2]
        assert any("Connection refused" in e for e in signals["errors"])

    async def test_keyless_platform_applies_without_a_saved_session(self, db_session):
        """MoveJobs/Tarve have no login concept the Connect flow even knows about — requiring
        a saved session before applying blocked every keyless board from ever being
        auto-applied to, even though discovery already reaches them with no account."""
        app = await _seed_app(db_session, platform="movejobs", url="https://movejobs.uk/jobs/x")
        history = FakeHistory(actions=["go_to_url", "done"], urls=["https://movejobs.uk/jobs/x"])

        with _mock_browser(db_session, history):
            result = await apply_mod.run_apply(db_session, app, redis=None)
            credential_store_mock = apply_mod.CredentialStore
            browser_profile_mock = apply_mod.build_browser_profile

        assert result.submitted is True
        credential_store_mock.return_value.load_session_cookies.assert_not_awaited()
        _, kwargs = browser_profile_mock.call_args
        assert kwargs["storage_state"] is None
        assert kwargs["allowed_domains"] is None

    async def test_authenticated_platform_restricts_to_its_real_registry_domain(self, db_session):
        """Domain-restriction must come from the source registry, not a guessed
        '{platform}.com' — reed.co.uk is a real counterexample to that guess (a platform key
        that never contained the ``.com`` the old logic assumed)."""
        app = await _seed_app(db_session, platform="reed", url="https://www.reed.co.uk/jobs/x")
        history = FakeHistory(actions=["go_to_url", "done"], urls=["https://www.reed.co.uk/jobs/x"])

        with _mock_browser(db_session, history):
            await apply_mod.run_apply(db_session, app, redis=None)
            browser_profile_mock = apply_mod.build_browser_profile

        _, kwargs = browser_profile_mock.call_args
        assert kwargs["allowed_domains"] is not None
        assert "https://reed.co.uk" in kwargs["allowed_domains"]
        assert not any(d.endswith(".com") for d in kwargs["allowed_domains"])


class TestReviewTask:
    async def test_loads_trajectory_and_runs_review(self, db_session):
        db_session.add(User(id=TEST_USER_ID, email="u@x.com", hashed_password="x"))
        await db_session.commit()
        traj = await record.record_trajectory(
            db_session, user_id=TEST_USER_ID, application_id="app1",
            platform="linkedin", status="completed",
        )

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=db_session)
        session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(tasks, "async_session_factory", return_value=session_cm), patch.object(
            tasks, "build_llm_client_for_user", new=AsyncMock(return_value=MagicMock())
        ), patch.object(
            tasks, "review_run",
            new=AsyncMock(return_value={"verdict": "success", "failure_class": None, "skill_id": None}),
        ) as review:
            await tasks.review_application_run({"redis": None}, traj.id, {"final_url": "x"})

        review.assert_awaited_once()
        assert review.await_args.args[2].id == traj.id

    async def test_missing_trajectory_is_noop(self, db_session):
        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=db_session)
        session_cm.__aexit__ = AsyncMock(return_value=False)
        with patch.object(tasks, "async_session_factory", return_value=session_cm), patch.object(
            tasks, "review_run", new=AsyncMock()
        ) as review:
            await tasks.review_application_run({"redis": None}, "nonexistent-id")
        review.assert_not_awaited()



async def test_an_unapproved_run_without_a_live_channel_asks_for_approval(db_session):
    """The DB-queue worker has no pub/sub to ask "submit now?" through. That used to reject
    every live submission (FAILED). Unapproved, it now stops before any browser opens and goes
    back for the owner's approval; approved, the approval is the confirmation."""
    import pytest

    from app.core.automation.runtime import apply as apply_mod

    app = await _seed_app(db_session, platform="careers:acme")
    app.resume_state = {}
    await db_session.commit()
    with pytest.raises(apply_mod.ApprovalRequiredError):
        await apply_mod.run_apply(db_session, app, redis=None)


def test_the_task_starts_at_the_apply_form_and_offers_the_cover_letter() -> None:
    from app.core.automation.runtime.apply import _build_task
    from app.models.job import Job

    job = Job(platform="careers:acme", title="PM", company="Acme",
              url="https://jobs.lever.co/acme/1", application_url="https://jobs.lever.co/acme/1/apply")
    task = _build_task(job, "/tmp/cv.pdf", "/tmp/cover.pdf")
    assert "URL: https://jobs.lever.co/acme/1/apply" in task
    assert "cover letter, upload the file at: /tmp/cover.pdf" in task
    assert "cover letter" not in _build_task(job, "/tmp/cv.pdf")


async def test_an_expired_session_is_refused_before_a_browser_opens(db_session) -> None:
    """An expired session used to drive the browser into the login wall, which then surfaced
    as a CAPTCHA pause rather than "reconnect"."""
    from datetime import UTC, datetime, timedelta

    import pytest

    from app.core.automation.runtime import apply as apply_mod
    from app.models.enums import SessionState
    from app.models.platform_session import PlatformSession

    db_session.add(User(id=TEST_USER_ID, email="u@x.com", hashed_password="x"))
    row = PlatformSession(user_id=TEST_USER_ID, platform="linkedin",
                          state=SessionState.SESSION_ACTIVE,
                          expires_at=datetime.now(UTC) - timedelta(days=1))
    db_session.add(row)
    await db_session.commit()
    with pytest.raises(apply_mod.ApplyPrerequisiteError, match="expired"):
        await apply_mod._require_unexpired_session(db_session, TEST_USER_ID, "linkedin")
    await db_session.refresh(row)
    assert row.state == SessionState.SESSION_EXPIRED


def test_session_expiry_comes_from_the_sign_in_cookie_not_a_tracking_cookie() -> None:
    from app.core.automation.connect import _earliest_expiry

    year = 1_900_000_000
    day = 1_800_000_000
    state = {"cookies": [{"name": "li_at", "expires": year}, {"name": "lidc", "expires": day}]}
    assert _earliest_expiry(state, ("li_at",)).timestamp() == year
    assert _earliest_expiry(state).timestamp() == day  # no hint: soonest cookie decides
