"""Phase 1.2: the Arq apply pipeline — idempotency, status lifecycle, retry classification."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq import Retry

from sqlalchemy import select

from app.models.agent_run import AgentRun
from app.models.application import Application
from app.models.application_event import ApplicationEvent
from app.models.enums import AgentName, AgentRunStatus, ApplicationEventType, ApplicationStatus, ApplyMode
from app.models.job import Job
from app.models.user_settings import UserSettings
from app.workers import tasks
from tests.conftest import TEST_USER_ID

CTX = {"job_try": 1, "redis": None}

#: A stored policy that objects to nothing, so these tests exercise submission mechanics
#: rather than the automation policy. Without it every application here escalates — the
#: shipped defaults review the first run on a portal, refuse an unscoreable posting, and
#: submit only inside working hours, all of which are true of a freshly seeded fixture.
#: The gate's own verdict routing is tested in ``TestPolicyGateRouting`` below.
PERMISSIVE_POLICY = {
    "review_first_run_per_source": False,
    "require_review_above_salary_k": 0,
    "min_ats_score": 0.0,
    "max_per_day": 0,
    "max_per_hour": 0,
    "min_seconds_between": 0,
    "max_per_company_per_week": 0,
    "reapply_cooldown_days": 0,
    "run_window": {"days": [], "start": "00:00", "end": "23:59", "timezone": "UTC"},
}


async def _seed_app(
    db, sample_job_data, status=ApplicationStatus.QUEUED, *, policy=PERMISSIVE_POLICY
) -> Application:
    job = Job(**sample_job_data)
    db.add(job)
    await db.flush()
    app = Application(
        user_id=TEST_USER_ID,
        job_id=job.id,
        status=status,
        apply_mode=ApplyMode.AUTONOMOUS,
        # The score the matching service records at discovery. Without one the policy
        # escalates rather than submitting an application it cannot vouch for.
        ats_score=0.9,
    )
    db.add(app)
    if policy is not None:
        db.add(UserSettings(user_id=TEST_USER_ID, automation=policy))
    await db.commit()
    await db.refresh(app)
    return app


class TestApplyPipeline:
    async def test_successful_apply_marks_applied(self, db_session, sample_job_data):
        app = await _seed_app(db_session, sample_job_data)
        await tasks._apply(db_session, CTX, app.id)
        await db_session.refresh(app)
        assert app.status == ApplicationStatus.APPLIED
        assert app.applied_at is not None

    async def test_terminal_outcome_emits_metric(self, db_session, sample_job_data):
        platform = sample_job_data["platform"]
        gauge = tasks.applications_total.labels(status="applied", platform=platform)
        before = gauge._value.get()
        app = await _seed_app(db_session, sample_job_data)
        await tasks._apply(db_session, CTX, app.id)
        assert gauge._value.get() == before + 1

    async def test_idempotent_when_already_applied(self, db_session, sample_job_data):
        app = await _seed_app(db_session, sample_job_data, status=ApplicationStatus.APPLIED)
        with patch.object(tasks, "_submit_application", new=AsyncMock()) as submit:
            await tasks._apply(db_session, CTX, app.id)
            submit.assert_not_awaited()

    async def test_transient_error_raises_retry_and_keeps_applying(
        self, db_session, sample_job_data
    ):
        app = await _seed_app(db_session, sample_job_data)
        with patch.object(
            tasks,
            "_submit_application",
            new=AsyncMock(side_effect=tasks.TransientApplyError("blip")),
        ):
            with pytest.raises(Retry):
                await tasks._apply(db_session, CTX, app.id)
        await db_session.refresh(app)
        assert app.status == ApplicationStatus.APPLYING  # in-flight marker persisted

    async def test_permanent_error_marks_failed(self, db_session, sample_job_data):
        app = await _seed_app(db_session, sample_job_data)
        with patch.object(
            tasks, "_submit_application", new=AsyncMock(side_effect=ValueError("boom"))
        ):
            await tasks._apply(db_session, CTX, app.id)
        await db_session.refresh(app)
        assert app.status == ApplicationStatus.FAILED
        assert "boom" in (app.notes or "")

    async def test_successful_apply_leaves_a_timeline_row(self, db_session, sample_job_data):
        """Pins a real gap: a clean submission committed the status change directly and
        skipped the timeline entirely — CAPTCHA pauses got a row, failures now do too
        (below), but the single most common outcome left no record of when or how the
        application was actually submitted."""
        app = await _seed_app(db_session, sample_job_data)
        await tasks._apply(db_session, CTX, app.id)
        events = (
            await db_session.execute(
                select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)
            )
        ).scalars().all()
        submitted = [e for e in events if e.event_type == ApplicationEventType.APPLICATION_SUBMITTED]
        assert len(submitted) == 1
        assert submitted[0].actor == "system"

    async def test_permanent_failure_leaves_a_timeline_row(self, db_session, sample_job_data):
        app = await _seed_app(db_session, sample_job_data)
        with patch.object(
            tasks, "_submit_application", new=AsyncMock(side_effect=ValueError("boom"))
        ):
            await tasks._apply(db_session, CTX, app.id)
        events = (
            await db_session.execute(
                select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)
            )
        ).scalars().all()
        errors = [e for e in events if e.event_type == ApplicationEventType.ERROR]
        assert len(errors) == 1
        assert "boom" in (errors[0].detail or "")

    async def test_missing_application_is_noop(self, db_session):
        await tasks._apply(db_session, CTX, "nonexistent-id")  # must not raise

    async def test_retry_exhaustion_marks_failed_not_stuck_applying(
        self, db_session, sample_job_data
    ):
        # On the final attempt a persistent transient failure must transition to terminal
        # FAILED (not raise Retry and leave the row stuck in APPLYING forever).
        app = await _seed_app(db_session, sample_job_data)
        ctx = {"job_try": tasks.MAX_TRIES, "redis": None}
        with patch.object(
            tasks, "_submit_application",
            new=AsyncMock(side_effect=tasks.TransientApplyError("anti-bot wall")),
        ):
            await tasks._apply(db_session, ctx, app.id)  # must NOT raise Retry
        await db_session.refresh(app)
        assert app.status == ApplicationStatus.FAILED
        assert "attempts" in (app.notes or "")


class TestHumanVerificationRequiredError:
    """A CAPTCHA/2FA wall pauses the application for the operator — it is not a failure,
    and the original run must not be treated as one."""

    async def test_pauses_for_review_instead_of_failing(self, db_session, sample_job_data):
        from app.core.automation.runtime.apply import HumanVerificationRequiredError

        app = await _seed_app(db_session, sample_job_data)
        with patch.object(
            tasks, "_submit_application",
            new=AsyncMock(
                side_effect=HumanVerificationRequiredError(
                    "CAPTCHA challenge before submit", url="https://example.com/apply/1"
                )
            ),
        ):
            await tasks._apply(db_session, CTX, app.id)  # must NOT raise

        await db_session.refresh(app)
        assert app.status == ApplicationStatus.PENDING_REVIEW
        assert app.application_url == "https://example.com/apply/1"
        assert app.resume_state == {"blocked_reason": "captcha"}
        assert app.paused_at is not None

    async def test_recomputes_next_action_to_complete_verification(
        self, db_session, sample_job_data
    ):
        from app.core.automation.runtime.apply import HumanVerificationRequiredError
        from app.models.enums import ApplicationHealth, NextAction

        app = await _seed_app(db_session, sample_job_data)
        with patch.object(
            tasks, "_submit_application",
            new=AsyncMock(side_effect=HumanVerificationRequiredError("2FA prompt")),
        ):
            await tasks._apply(db_session, CTX, app.id)

        await db_session.refresh(app)
        assert app.next_action == NextAction.COMPLETE_VERIFICATION
        assert app.health == ApplicationHealth.BLOCKED

    async def test_publishes_an_intervention_required_event_with_the_url(
        self, db_session, sample_job_data
    ):
        from app.core.automation.runtime.apply import HumanVerificationRequiredError

        app = await _seed_app(db_session, sample_job_data)
        pool = _fake_pool()
        with patch.object(
            tasks, "_submit_application",
            new=AsyncMock(
                side_effect=HumanVerificationRequiredError("CAPTCHA", url="https://x.com/apply")
            ),
        ), patch("app.workers.tasks.publish_progress", new=AsyncMock()) as published:
            await tasks._apply(db_session, {"job_try": 1, "redis": pool}, app.id)

        # Two distinct events: a generic status update (refreshes the applications list) and
        # the specific intervention_required event (opens the modal) — find the latter.
        events = [call.args[2] for call in published.await_args_list]
        intervention_events = [e for e in events if e["type"] == "intervention_required"]
        assert len(intervention_events) == 1
        payload = intervention_events[0]["payload"]
        assert payload["kind"] == "captcha"
        assert payload["url"] == "https://x.com/apply"
        assert payload["application_id"] == app.id


class TestTransientClassification:
    def test_is_transient(self):
        assert tasks._is_transient(RuntimeError("Rate limit exceeded (429)"))
        assert tasks._is_transient(RuntimeError("Connection reset by peer"))
        assert tasks._is_transient(RuntimeError("service temporarily unavailable"))
        assert not tasks._is_transient(RuntimeError("required form field missing"))

    async def test_submit_reclassifies_transient_infra_error(self, db_session, sample_job_data):
        app = await _seed_app(db_session, sample_job_data)
        fake_settings = MagicMock()
        fake_settings.browser.live_apply = True
        with patch.object(tasks, "get_settings", return_value=fake_settings), patch(
            "app.core.automation.runtime.apply.run_apply",
            new=AsyncMock(side_effect=RuntimeError("429 Too Many Requests")),
        ):
            with pytest.raises(tasks.TransientApplyError):
                await tasks._submit_application(db_session, app)

    async def test_submit_keeps_terminal_error_terminal(self, db_session, sample_job_data):
        app = await _seed_app(db_session, sample_job_data)
        fake_settings = MagicMock()
        fake_settings.browser.live_apply = True
        with patch.object(tasks, "get_settings", return_value=fake_settings), patch(
            "app.core.automation.runtime.apply.run_apply",
            new=AsyncMock(side_effect=RuntimeError("required form field missing")),
        ):
            with pytest.raises(RuntimeError) as exc:  # NOT reclassified to TransientApplyError
                await tasks._submit_application(db_session, app)
            assert not isinstance(exc.value, tasks.TransientApplyError)


class TestPublish:
    async def test_publish_no_redis_is_noop(self):
        await tasks._publish({"redis": None}, TEST_USER_ID, "app-1", "applying")


def _fake_pool() -> MagicMock:
    """An Arq pool stand-in. ``publish`` must be awaitable too — the worker uses the same
    connection for the progress bus, so a bare MagicMock fails inside the publish, not the
    enqueue, and the traceback points at the wrong thing."""
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="j1"))
    pool.llen = AsyncMock(return_value=0)
    pool.publish = AsyncMock(return_value=0)
    return pool


class TestPolicyGateRouting:
    """Each policy verdict has a different resting place, and conflating them is what
    produces dead ends: a held application must come back, an escalated one must reach a
    human, and a blocked one must stop without pretending to be a system failure."""

    async def test_an_allowed_application_submits(self, db_session, sample_job_data):
        app = await _seed_app(db_session, sample_job_data)
        await tasks._apply(db_session, CTX, app.id)
        await db_session.refresh(app)
        assert app.status == ApplicationStatus.APPLIED

    async def test_a_hold_re_queues_with_a_wake_up_time_and_does_not_submit(
        self, db_session, sample_job_data
    ):
        app = await _seed_app(
            db_session, sample_job_data, policy={**PERMISSIVE_POLICY, "paused": True}
        )
        pool = _fake_pool()
        with patch.object(tasks, "_submit_application", new=AsyncMock()) as submit:
            await tasks._apply(db_session, {"job_try": 1, "redis": pool}, app.id)
            submit.assert_not_awaited()

        await db_session.refresh(app)
        assert app.status == ApplicationStatus.QUEUED
        assert "paused" in (app.notes or "").lower()
        assert pool.enqueue_job.await_count == 1
        assert pool.enqueue_job.await_args.kwargs["_defer_by"] > 0

    async def test_the_re_queue_does_not_collide_with_the_running_job_id(
        self, db_session, sample_job_data
    ):
        """The default job id is derived from the application id and is still held by this
        very run, so re-queueing under it would be silently deduplicated away and the
        application would never wake up."""
        app = await _seed_app(
            db_session, sample_job_data, policy={**PERMISSIVE_POLICY, "paused": True}
        )
        pool = _fake_pool()
        await tasks._apply(db_session, {"job_try": 1, "redis": pool}, app.id)

        assert pool.enqueue_job.await_args.kwargs["_job_id"] != f"apply:{app.id}"

    async def test_an_escalation_stages_for_review_rather_than_failing(
        self, db_session, sample_job_data
    ):
        """A role above the review threshold is not a failure — marking it FAILED would bury
        a perfectly good application in the same bucket as a broken portal."""
        sample_job_data = {**sample_job_data, "salary_range": "£150,000 - £180,000"}
        app = await _seed_app(
            db_session,
            sample_job_data,
            policy={**PERMISSIVE_POLICY, "require_review_above_salary_k": 120},
        )
        with patch.object(tasks, "_submit_application", new=AsyncMock()) as submit:
            await tasks._apply(db_session, CTX, app.id)
            submit.assert_not_awaited()

        await db_session.refresh(app)
        assert app.status == ApplicationStatus.PENDING_REVIEW
        assert "180" in (app.notes or ""), "the reason quotes the top of the band"

    async def test_an_escalation_is_visible_on_the_live_agent_graph(
        self, db_session, sample_job_data
    ):
        """A policy escalation is a real agent outcome, not a silent early return — before
        this, only runs that reached submission wrote an AgentRun, so the (common,
        review-mode) escalate/hold/block outcomes never showed up on the Agent Ops view."""
        sample_job_data = {**sample_job_data, "salary_range": "£150,000 - £180,000"}
        app = await _seed_app(
            db_session,
            sample_job_data,
            policy={**PERMISSIVE_POLICY, "require_review_above_salary_k": 120},
        )
        with patch.object(tasks, "_submit_application", new=AsyncMock()):
            await tasks._apply(db_session, CTX, app.id)

        run = (
            await db_session.execute(
                select(AgentRun).where(
                    AgentRun.linked_entity_id == app.id, AgentRun.agent_name == AgentName.APPLICATION
                )
            )
        ).scalar_one()
        assert run.status == AgentRunStatus.NEEDS_REVIEW
        assert "180" in (run.output_summary or "")
        assert run.finished_at is not None

    async def test_a_block_is_terminal_and_says_which_rule_stopped_it(
        self, db_session, sample_job_data
    ):
        app = await _seed_app(
            db_session,
            sample_job_data,
            policy={**PERMISSIVE_POLICY, "blocked_companies": [sample_job_data["company"]]},
        )
        with patch.object(tasks, "_submit_application", new=AsyncMock()) as submit:
            await tasks._apply(db_session, CTX, app.id)
            submit.assert_not_awaited()

        await db_session.refresh(app)
        assert app.status == ApplicationStatus.FAILED
        assert "blocked-employers" in (app.notes or "")

    async def test_a_held_application_never_reaches_the_submit_call_at_all(
        self, db_session, sample_job_data
    ):
        """The gate runs before the APPLYING marker, so a hold leaves no in-flight row
        behind — that is what lets the re-queue pick it up cleanly."""
        app = await _seed_app(
            db_session, sample_job_data, policy={**PERMISSIVE_POLICY, "paused": True}
        )
        await tasks._apply(db_session, CTX, app.id)
        await db_session.refresh(app)
        assert app.status != ApplicationStatus.APPLYING
