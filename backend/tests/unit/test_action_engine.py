"""Next Best Action engine.

The command centre's value rests entirely on this: if the ranking is wrong, the user misses
the one thing that mattered. These tests pin the *ordering decisions* rather than exact
scores, so the weights can be retuned without rewriting the suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.actions.engine import apply_verdict, compute_action
from app.models.application import Application
from app.models.enums import (
    ActionPriority,
    ApplicationHealth,
    ApplicationStatus,
    NextAction,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

#: Fields the engine reads. Set explicitly because a bare Application() leaves column
#: defaults unapplied until a flush, and the engine must not depend on database round-trips.
_BLANK = {
    "assessment_due_at": None,
    "interview_at": None,
    "paused_at": None,
    "applied_at": None,
    "resume_state": None,
    "document_version_id": None,
    "follow_up_due_at": None,
}


def app(**kw: object) -> Application:
    a = Application()
    defaults = {
        "status": ApplicationStatus.QUEUED,
        "health": ApplicationHealth.HEALTHY,
        "ats_score": 0.8,
        "created_at": NOW - timedelta(days=1),
        "resume_id": "resume-1",
        **_BLANK,
    }
    defaults.update(kw)
    for key, value in defaults.items():
        setattr(a, key, value)
    return a


class TestDeadlineDrivenActions:
    def test_an_imminent_assessment_is_the_top_priority(self) -> None:
        v = compute_action(
            app(status=ApplicationStatus.APPLIED, assessment_due_at=NOW + timedelta(hours=4)),
            now=NOW,
        )
        assert v.action is NextAction.COMPLETE_ASSESSMENT
        assert v.priority is ActionPriority.HIGH
        assert "4 hours" in v.reason

    def test_an_overdue_assessment_scores_above_a_future_one(self) -> None:
        overdue = compute_action(app(assessment_due_at=NOW - timedelta(hours=2)), now=NOW)
        later = compute_action(app(assessment_due_at=NOW + timedelta(days=5)), now=NOW)
        assert overdue.score > later.score
        assert "overdue" in overdue.reason

    def test_the_nearer_hard_deadline_wins(self) -> None:
        v = compute_action(
            app(
                assessment_due_at=NOW + timedelta(hours=3),
                interview_at=NOW + timedelta(days=6),
            ),
            now=NOW,
        )
        assert v.action is NextAction.COMPLETE_ASSESSMENT

    def test_an_upcoming_interview_is_surfaced(self) -> None:
        v = compute_action(
            app(status=ApplicationStatus.INTERVIEW, interview_at=NOW + timedelta(hours=20)),
            now=NOW,
        )
        assert v.action is NextAction.PREPARE_INTERVIEW
        assert v.priority is ActionPriority.HIGH


class TestNoDeadEnds:
    """Every recoverable blocker must produce something the user can actually do."""

    def test_a_failed_application_with_saved_state_offers_resume(self) -> None:
        v = compute_action(
            app(
                status=ApplicationStatus.FAILED,
                resume_state={"current": "work_authorisation"},
            ),
            now=NOW,
        )
        assert v.action is NextAction.RESUME_APPLICATION
        assert v.health is ApplicationHealth.BLOCKED
        assert "work_authorisation" in v.reason

    def test_a_captcha_wall_asks_for_verification_not_a_generic_resume(self) -> None:
        """A CAPTCHA/2FA pause (workers.tasks._mark_needs_verification) is a distinct,
        more specific action than the generic 'resume from where it stopped' — the operator
        needs to know a browser window is waiting on them, not just that a run is paused."""
        v = compute_action(
            app(
                status=ApplicationStatus.PENDING_REVIEW,
                resume_state={"blocked_reason": "captcha"},
            ),
            now=NOW,
        )
        assert v.action is NextAction.COMPLETE_VERIFICATION
        assert v.health is ApplicationHealth.BLOCKED
        assert "browser window" in v.reason

    def test_pending_review_without_a_captcha_marker_is_the_generic_review_action(self) -> None:
        """A plain 'needs the operator's review' application must not be swept up by the
        CAPTCHA rule just because it also happens to be PENDING_REVIEW."""
        v = compute_action(app(status=ApplicationStatus.PENDING_REVIEW), now=NOW)
        assert v.action is NextAction.REVIEW_APPLICATION

    def test_a_long_paused_application_asks_for_a_reconnect(self) -> None:
        v = compute_action(
            app(status=ApplicationStatus.APPLYING, paused_at=NOW - timedelta(hours=5)),
            now=NOW,
        )
        assert v.action is NextAction.RELOGIN
        assert v.health is ApplicationHealth.SESSION_REQUIRED

    def test_a_queued_application_without_a_cv_asks_for_one(self) -> None:
        v = compute_action(
            app(status=ApplicationStatus.QUEUED, resume_id=None), now=NOW
        )
        assert v.action is NextAction.UPLOAD_CV
        assert v.health is ApplicationHealth.DOCUMENT_REQUIRED

    def test_an_unconfirmed_submission_asks_for_verification(self) -> None:
        v = compute_action(
            app(
                status=ApplicationStatus.APPLIED,
                health=ApplicationHealth.STATUS_UNKNOWN,
                applied_at=NOW - timedelta(days=1),
            ),
            now=NOW,
        )
        assert v.action is NextAction.VERIFY_SUBMISSION


class TestFollowUpLifecycle:
    def test_a_recent_submission_is_left_alone(self) -> None:
        v = compute_action(
            app(status=ApplicationStatus.APPLIED, applied_at=NOW - timedelta(days=2)),
            now=NOW,
        )
        assert v.action is NextAction.WAIT
        assert v.health is ApplicationHealth.HEALTHY

    def test_silence_past_a_week_prompts_a_follow_up(self) -> None:
        v = compute_action(
            app(status=ApplicationStatus.APPLIED, applied_at=NOW - timedelta(days=9)),
            now=NOW,
        )
        assert v.action is NextAction.FOLLOW_UP

    def test_a_very_old_application_stops_nagging(self) -> None:
        """Past a month it is realistically closed; continuing to prompt is noise."""
        v = compute_action(
            app(status=ApplicationStatus.APPLIED, applied_at=NOW - timedelta(days=40)),
            now=NOW,
        )
        assert v.action is NextAction.WAIT
        assert v.health is ApplicationHealth.STALE


class TestPrioritisation:
    def test_a_later_hiring_stage_outranks_an_earlier_one(self) -> None:
        """Losing an interview to an unnoticed blocker costs more than losing a queued job."""
        interview = compute_action(
            app(
                status=ApplicationStatus.INTERVIEW,
                assessment_due_at=NOW + timedelta(hours=5),
            ),
            now=NOW,
        )
        queued = compute_action(
            app(status=ApplicationStatus.QUEUED, assessment_due_at=NOW + timedelta(hours=5)),
            now=NOW,
        )
        assert interview.score > queued.score

    def test_terminal_applications_need_nothing(self) -> None:
        for status in (ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN):
            v = compute_action(app(status=status), now=NOW)
            assert v.action is NextAction.NONE
            assert v.priority is ActionPriority.NONE
            assert v.is_actionable is False

    def test_every_reason_is_human_readable(self) -> None:
        """The queue renders this string verbatim; a leaked enum name would be a bug."""
        for status in ApplicationStatus:
            v = compute_action(app(status=status), now=NOW)
            assert v.reason
            assert v.reason[0].isupper()
            assert v.reason.endswith(".")


class TestApplyVerdict:
    def test_writing_a_new_verdict_reports_a_change(self) -> None:
        a = app(status=ApplicationStatus.PENDING_REVIEW)
        assert apply_verdict(a, compute_action(a, now=NOW)) is True
        assert a.next_action is NextAction.REVIEW_APPLICATION

    def test_recomputing_the_same_verdict_reports_no_change(self) -> None:
        """Without this a scheduled sweep writes a duplicate timeline entry every run."""
        a = app(status=ApplicationStatus.PENDING_REVIEW)
        apply_verdict(a, compute_action(a, now=NOW))
        assert apply_verdict(a, compute_action(a, now=NOW)) is False


class TestQueueOrdering:
    """Whole-queue ordering. Unit rules can each be right while the ranking is still wrong.

    Every assertion here failed against the first tuning: an assessment three hours out
    ranked *below* an interview 21 hours away, because the interview's later hiring stage
    outweighed the nearer deadline, and blockers scored below a routine follow-up nudge.
    """

    def _queue(self) -> list[tuple[str, float, ActionPriority]]:
        cases = [
            app(status=ApplicationStatus.APPLIED, assessment_due_at=NOW + timedelta(hours=3)),
            app(status=ApplicationStatus.INTERVIEW, interview_at=NOW + timedelta(hours=21)),
            app(status=ApplicationStatus.APPLYING, paused_at=NOW - timedelta(hours=5)),
            app(status=ApplicationStatus.FAILED, resume_state={"current": "salary"}),
            app(status=ApplicationStatus.QUEUED, resume_id=None),
            app(status=ApplicationStatus.PENDING_REVIEW),
            app(status=ApplicationStatus.APPLIED, applied_at=NOW - timedelta(days=9)),
        ]
        verdicts = [compute_action(c, now=NOW) for c in cases]
        ranked = sorted(verdicts, key=lambda v: -v.score)
        return [(v.action.value, v.score, v.priority) for v in ranked]

    def test_the_nearest_hard_deadline_ranks_first(self) -> None:
        order = [a for a, _, _ in self._queue()]
        assert order[0] == NextAction.COMPLETE_ASSESSMENT.value
        assert order[1] == NextAction.PREPARE_INTERVIEW.value

    def test_blockers_outrank_a_routine_follow_up(self) -> None:
        """A stuck application must not sit below an optional nudge."""
        scores = {a: s for a, s, _ in self._queue()}
        follow_up = scores[NextAction.FOLLOW_UP.value]
        for blocker in (
            NextAction.RELOGIN.value,
            NextAction.RESUME_APPLICATION.value,
            NextAction.UPLOAD_CV.value,
            NextAction.REVIEW_APPLICATION.value,
        ):
            assert scores[blocker] > follow_up, f"{blocker} should outrank a follow-up"

    def test_the_three_bands_mean_three_different_things(self) -> None:
        bands = {a: p for a, _, p in self._queue()}
        assert bands[NextAction.COMPLETE_ASSESSMENT.value] is ActionPriority.HIGH
        assert bands[NextAction.RELOGIN.value] is ActionPriority.MEDIUM
        assert bands[NextAction.FOLLOW_UP.value] is ActionPriority.LOW
