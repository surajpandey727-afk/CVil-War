"""The layer that turns database state into a policy decision.

The engine is tested in isolation in ``tests/unit/test_policy_engine.py``. What is tested here
is the part the engine cannot check: that the facts handed to it are the real ones. A rule
that works perfectly on a context nobody assembled correctly is worth nothing.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.policy import AutomationPolicy, Verdict
from app.models.application import Application
from app.models.application_event import ApplicationEvent
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.user_settings import UserSettings
from app.services.policy import (
    build_context,
    gate,
    load_policy,
    parse_salary_k,
    titles_are_similar,
)
from tests.conftest import TEST_USER_ID

_JOB_SEQ = itertools.count(1)


def _job(db, **overrides):  # type: ignore[no-untyped-def]
    # A distinct posting each call. ``applications`` carries a partial unique index on
    # (user_id, job_id) for non-terminal statuses, so several live applications in one test
    # need several jobs — which is also what the real system produces.
    data = {
        # Set explicitly rather than waiting for the column default, which is only applied at
        # flush — the applications below need the id before that.
        "id": uuid4().hex,
        "user_id": TEST_USER_ID,
        "platform": "careers:monzo",
        "platform_job_id": f"j{next(_JOB_SEQ)}",
        "title": "Senior Product Manager",
        "company": "Monzo",
        "location": "London",
        "url": "https://example.invalid/j1",
        "description": "",
        "status": "new",
    }
    job = Job(**{**data, **overrides})
    db.add(job)
    return job


def _application(db, job, **overrides):  # type: ignore[no-untyped-def]
    data = {
        "user_id": TEST_USER_ID,
        "job_id": job.id,
        "apply_mode": "review",
        "status": ApplicationStatus.QUEUED,
    }
    app = Application(**{**data, **overrides})
    db.add(app)
    return app


#: A policy with everything optional switched off, so a test that sets one clause is testing
#: that clause. Without it the defaults (first-run review, the Mon-Fri window) fire too and
#: the assertion passes or fails on what day the suite happens to run.
PERMISSIVE = {
    "review_first_run_per_source": False,
    "require_review_above_salary_k": 0,
    "run_window": {"days": [], "start": "00:00", "end": "23:59", "timezone": "UTC"},
}


class TestSalaryParsing:
    """Salary arrives as free text, and the difference between 'no band' and 'zero' decides
    whether most of the UK market is silently discarded."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("£75,000 - £95,000", 95),
            ("75000-95000 GBP", 95),
            ("£80k", 80),
            ("Up to £120,000 per annum", 120),
            ("Competitive", None),
            ("", None),
            (None, None),
            ("£450 per day", None),  # a day rate is not an annual band
        ],
    )
    def test_top_of_band(self, raw, expected) -> None:  # type: ignore[no-untyped-def]
        assert parse_salary_k(raw) == expected


class TestTitleSimilarity:
    """Drives the §3.2 re-application cooldown."""

    def test_seniority_prefixes_do_not_make_two_titles_different_roles(self) -> None:
        assert titles_are_similar("Senior Product Manager", "Product Manager")
        assert titles_are_similar("Lead Data Engineer", "Data Engineer")

    def test_genuinely_different_roles_are_not_conflated(self) -> None:
        assert not titles_are_similar("Product Manager", "Security Engineer")
        assert not titles_are_similar("Product Manager", "Head of Finance")

    def test_an_empty_title_is_never_similar_to_anything(self) -> None:
        """Otherwise a posting with no title would collide with every past application and
        hold the whole queue behind a cooldown that never applied."""
        assert not titles_are_similar("", "Product Manager")


class TestLoadPolicy:
    async def test_a_user_with_no_settings_row_gets_the_shipped_defaults(
        self, db_session, current_user
    ) -> None:
        policy = await load_policy(db_session, current_user.id)
        assert policy == AutomationPolicy()

    async def test_a_threshold_set_on_the_old_settings_screen_is_not_reset(
        self, db_session, current_user
    ) -> None:
        """``min_ats_score`` had its own column before the policy blob existed. Loading the
        defaults over it would quietly lower a threshold the operator had chosen."""
        db_session.add(UserSettings(user_id=current_user.id, min_ats_score=0.9))
        await db_session.commit()
        policy = await load_policy(db_session, current_user.id)
        assert policy.min_ats_score == 0.9

    async def test_the_stored_blob_wins_once_one_exists(
        self, db_session, current_user
    ) -> None:
        db_session.add(
            UserSettings(
                user_id=current_user.id,
                min_ats_score=0.9,
                automation={"min_ats_score": 0.5, "max_per_day": 3},
            )
        )
        await db_session.commit()
        policy = await load_policy(db_session, current_user.id)
        assert policy.min_ats_score == 0.5
        assert policy.max_per_day == 3


class TestContextCounting:
    async def test_only_real_submissions_count_towards_the_daily_cap(
        self, db_session, current_user
    ) -> None:
        """A FAILED attempt never reached the employer. Counting it would spend the
        operator's daily allowance on the system's own outage."""
        now = datetime.now(UTC)
        for status in (
            ApplicationStatus.APPLIED,
            ApplicationStatus.FAILED,
            ApplicationStatus.QUEUED,
        ):
            _application(
                db_session,
                _job(db_session),
                status=status,
                applied_at=now.replace(tzinfo=None),
            )
        job = _job(db_session)
        candidate = _application(db_session, job)
        await db_session.commit()

        ctx = await build_context(db_session, candidate, job, now=now)
        assert ctx.submitted_today == 1

    async def test_an_old_submission_falls_out_of_the_window(
        self, db_session, current_user
    ) -> None:
        now = datetime.now(UTC)
        _application(
            db_session,
            _job(db_session),
            status=ApplicationStatus.APPLIED,
            applied_at=(now - timedelta(days=3)).replace(tzinfo=None),
        )
        job = _job(db_session)
        candidate = _application(db_session, job)
        await db_session.commit()

        ctx = await build_context(db_session, candidate, job, now=now)
        assert ctx.submitted_today == 0
        # Three days is outside the daily window and inside the weekly one — the two counts
        # read the same rows through different cutoffs, which is exactly what could go wrong.
        assert ctx.submitted_to_company_this_week == 1

    async def test_the_application_being_judged_is_not_counted_against_itself(
        self, db_session, current_user
    ) -> None:
        """It has no ``applied_at`` yet, but the spacing query must exclude it regardless —
        otherwise a retry of an already-applied row would hold behind its own timestamp."""
        job = _job(db_session)
        await db_session.commit()
        now = datetime.now(UTC)
        candidate = _application(
            db_session,
            job,
            status=ApplicationStatus.APPLIED,
            applied_at=now.replace(tzinfo=None),
        )
        await db_session.commit()

        ctx = await build_context(db_session, candidate, job, now=now)
        assert ctx.seconds_since_last_submission is None

    async def test_a_posting_already_rejected_is_still_a_duplicate(
        self, db_session, current_user
    ) -> None:
        """The ``uq_app_active_job`` index only covers live statuses, so re-applying to a
        posting that already rejected you is the case the database does not catch — and the
        one most likely to reach a recruiter as an obviously automated second attempt."""
        job = _job(db_session)
        await db_session.commit()
        earlier = _application(db_session, job, status=ApplicationStatus.REJECTED)
        candidate = _application(db_session, job)
        await db_session.commit()

        ctx = await build_context(db_session, candidate, job)
        assert ctx.duplicate_of_application_id == earlier.id

    async def test_the_same_posting_found_through_two_sources_is_still_a_duplicate(
        self, db_session, current_user
    ) -> None:
        """The same vacancy routinely arrives as two Job rows — once from the employer's own
        board and once from an aggregator. Matching on job_id alone would let the system
        apply twice to one posting, which is §3.1's whole subject."""
        first = _job(db_session, platform_job_id="j1", canonical_job_id="canon-1")
        second = _job(db_session, platform="adzuna", platform_job_id="j2",
                      canonical_job_id="canon-1")
        await db_session.commit()
        earlier = _application(db_session, first, status=ApplicationStatus.APPLIED)
        candidate = _application(db_session, second)
        await db_session.commit()

        ctx = await build_context(db_session, candidate, second)
        assert ctx.duplicate_of_application_id == earlier.id

    async def test_a_similar_role_at_the_same_employer_sets_the_cooldown_clock(
        self, db_session, current_user
    ) -> None:
        applied_job = _job(db_session, platform_job_id="old", title="Product Manager")
        new_job = _job(db_session, platform_job_id="new", title="Senior Product Manager")
        await db_session.commit()
        when = datetime.now(UTC) - timedelta(days=10)
        _application(
            db_session,
            applied_job,
            status=ApplicationStatus.APPLIED,
            applied_at=when.replace(tzinfo=None),
        )
        candidate = _application(db_session, new_job)
        await db_session.commit()

        ctx = await build_context(db_session, candidate, new_job)
        assert ctx.last_similar_application_at is not None

    async def test_an_unrelated_role_at_the_same_employer_does_not(
        self, db_session, current_user
    ) -> None:
        applied_job = _job(db_session, platform_job_id="old", title="Security Engineer")
        new_job = _job(db_session, platform_job_id="new", title="Product Manager")
        await db_session.commit()
        _application(
            db_session,
            applied_job,
            status=ApplicationStatus.APPLIED,
            applied_at=datetime.now(UTC).replace(tzinfo=None),
        )
        candidate = _application(db_session, new_job)
        await db_session.commit()

        ctx = await build_context(db_session, candidate, new_job)
        assert ctx.last_similar_application_at is None

    async def test_a_portal_never_used_before_is_flagged_as_a_first_run(
        self, db_session, current_user
    ) -> None:
        job = _job(db_session)
        await db_session.commit()
        candidate = _application(db_session, job)
        await db_session.commit()

        ctx = await build_context(db_session, candidate, job)
        assert ctx.first_run_on_source is True

    async def test_a_success_resets_the_consecutive_failure_count(
        self, db_session, current_user
    ) -> None:
        """The circuit breaker is about a portal that is broken *now*. Counting failures from
        before the last success would suspend a portal that had since recovered."""
        base = datetime.now(UTC).replace(tzinfo=None)
        for offset, status in enumerate(
            (
                ApplicationStatus.FAILED,
                ApplicationStatus.FAILED,
                ApplicationStatus.APPLIED,  # the most recent outcome
            )
        ):
            app = _application(db_session, _job(db_session), status=status)
            app.updated_at = base + timedelta(minutes=offset)
        job = _job(db_session)
        candidate = _application(db_session, job)
        candidate.updated_at = base - timedelta(minutes=1)
        await db_session.commit()

        ctx = await build_context(db_session, candidate, job)
        assert ctx.consecutive_source_failures == 0
        assert ctx.first_run_on_source is False


class TestGateRecordsItsReasoning:
    """Policy §9: the operator can always answer 'why hasn't it applied to this?' without
    reading logs."""

    async def test_a_refusal_lands_on_the_timeline_with_the_rule_ids(
        self, db_session, current_user
    ) -> None:
        db_session.add(
            UserSettings(
                user_id=current_user.id, automation={**PERMISSIVE, "paused": True}
            )
        )
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        decision = await gate(db_session, app, ats_score=0.9)
        await db_session.commit()

        assert decision.verdict is Verdict.HOLD
        events = (await db_session.execute(ApplicationEvent.__table__.select())).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["verdict"] == "hold"
        assert "oversight.kill_switch" in [o["rule_id"] for o in payload["outcomes"]]

    async def test_an_unremarkable_allow_is_not_written_down(
        self, db_session, current_user
    ) -> None:
        """One 'policy allowed this' entry per application would bury the entries that
        matter under noise."""
        db_session.add(
            UserSettings(
                user_id=current_user.id,
                automation=PERMISSIVE,
            )
        )
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        decision = await gate(db_session, app, ats_score=0.99)
        await db_session.commit()

        assert decision.verdict is Verdict.ALLOW
        events = (await db_session.execute(ApplicationEvent.__table__.select())).all()
        assert events == []
