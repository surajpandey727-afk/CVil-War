"""Next Best Action — what the user should do about an application, and how urgently.

The command centre's whole premise is that a status list is not useful. "SUBMITTED" tells the
user nothing actionable; "assessment closes in 4 hours" does. This module turns each
application's state into a single concrete action plus a transparent reason.

Two rules shape the design:

**No dead ends.** Every recoverable blocker maps to an action. A failed application is never
just FAILED — it is "session expired, reconnect" or "verification required, complete it".
An unrecoverable state is the only case that yields no action, and it says why.

**Explain the ranking.** Priority is ``urgency x opportunity x consequence``, and the reason
string states the dominant factor in plain English. A queue the user cannot second-guess is a
queue they stop trusting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.application import Application
from app.models.enums import (
    ActionPriority,
    ApplicationHealth,
    ApplicationStatus,
    NextAction,
)

#: Applications with no update after this long are worth chasing.
FOLLOW_UP_AFTER_DAYS = 7
#: Beyond this, a submitted application is realistically dead; stop nagging.
STALE_AFTER_DAYS = 30
#: A started-but-unfinished application older than this is treated as abandoned.
PAUSED_STALE_HOURS = 3

#: Score thresholds for the queue's colour bands, set against real output so the three bands
#: mean three genuinely different things:
#:   HIGH   — a clock is running and missing it ends the application (assessment, interview).
#:   MEDIUM — nothing is moving until the user acts (expired session, missing CV, review).
#:   LOW    — worth doing, nothing breaks if it waits (follow-up nudges).
#: At MEDIUM=25 a blocked application scored 23 and sat in the same band as a 7-day follow-up
#: nudge, which understated it: one is stuck, the other is optional.
_HIGH = 60.0
_MEDIUM = 12.0


@dataclass(frozen=True)
class ActionVerdict:
    """The computed action for one application."""

    action: NextAction
    health: ApplicationHealth
    reason: str
    score: float
    priority: ActionPriority
    due_at: datetime | None = None

    @property
    def is_actionable(self) -> bool:
        return self.action not in (NextAction.NONE, NextAction.WAIT)


def _hours_until(when: datetime | None, now: datetime) -> float | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (when - now).total_seconds() / 3600.0


def _days_since(when: datetime | None, now: datetime) -> float | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (now - when).total_seconds() / 86400.0


#: Urgency for an action with no deadline. A blocked application has no clock running, but
#: it is stuck: leaving it at the no-op baseline ranked "session expired, cannot proceed"
#: below "submitted 9 days ago", which is the wrong way round — one is blocking progress and
#: the other is a nudge.
BLOCKING_URGENCY = 6.0
IDLE_URGENCY = 1.0


def _urgency_from_deadline(hours: float | None, *, default: float = IDLE_URGENCY) -> float:
    """Urgency from a deadline, on a deliberately steep curve.

    The gap between bands has to be wide enough that urgency dominates the other factors.
    Tuned against real output: at a shallower curve an assessment closing in 3 hours scored
    *below* an interview 21 hours away, because the interview's later hiring stage
    outweighed the nearer deadline. Missing the assessment ends the application outright,
    so time-to-deadline has to win.
    """
    if hours is None:
        return default
    if hours <= 0:
        return 16.0      # overdue — nothing outranks this
    if hours <= 6:
        return 12.0
    if hours <= 24:
        return 7.0
    if hours <= 72:
        return 4.0
    if hours <= 168:
        return 2.0
    return 1.0


def _opportunity(app: Application) -> float:
    """How valuable this application is, 1-3.

    Later hiring stages are worth more: losing an interview to an unnoticed blocker costs far
    more than losing a queued application that was never submitted.
    """
    stage_value = {
        ApplicationStatus.OFFER: 3.0,
        ApplicationStatus.INTERVIEW: 2.6,
        ApplicationStatus.APPLIED: 1.6,
        ApplicationStatus.APPROVED: 1.3,
        ApplicationStatus.APPLYING: 1.3,
        ApplicationStatus.PENDING_REVIEW: 1.1,
        ApplicationStatus.QUEUED: 1.0,
    }
    base = stage_value.get(app.status, 1.0)
    # A strong ATS match is worth chasing harder than a marginal one.
    if app.ats_score:
        base *= 1.0 + min(app.ats_score, 1.0) * 0.5
    return base


def compute_action(app: Application, *, now: datetime | None = None) -> ActionVerdict:
    """Decide the single next action for one application.

    Ordered by consequence, not by convenience: a hard external deadline beats an internal
    housekeeping task, and anything that blocks progress beats anything that merely improves
    it. The first matching rule wins, so the list reads as a priority ladder.
    """
    now = now or datetime.now(UTC)

    def verdict(
        action: NextAction,
        health: ApplicationHealth,
        reason: str,
        consequence: float,
        due: datetime | None = None,
        *,
        base_urgency: float = IDLE_URGENCY,
    ) -> ActionVerdict:
        urgency = _urgency_from_deadline(_hours_until(due, now), default=base_urgency)
        score = urgency * _opportunity(app) * consequence
        priority = (
            ActionPriority.HIGH
            if score >= _HIGH
            else ActionPriority.MEDIUM
            if score >= _MEDIUM
            else ActionPriority.LOW
        )
        return ActionVerdict(action, health, reason, round(score, 2), priority, due)

    # 1. Assessments — an external, hard deadline. Miss it and the application is over.
    if app.assessment_due_at and app.status not in _TERMINAL:
        hours = _hours_until(app.assessment_due_at, now)
        when = "overdue" if (hours or 0) <= 0 else f"due in {_humanise(hours)}"
        return verdict(
            NextAction.COMPLETE_ASSESSMENT,
            ApplicationHealth.ACTION_REQUIRED,
            f"Assessment {when}.",
            3.0,
            app.assessment_due_at,
        )

    # 2. Interviews — also externally scheduled and unmissable.
    if app.interview_at and app.status not in _TERMINAL:
        hours = _hours_until(app.interview_at, now)
        if hours is not None and hours > -12:
            return verdict(
                NextAction.PREPARE_INTERVIEW,
                ApplicationHealth.NEEDS_ATTENTION,
                f"Interview in {_humanise(hours)}.",
                2.5,
                app.interview_at,
            )

    # 3. Blocked mid-application. Recoverable, and the work already done is at risk — this is
    #    the case that used to surface as a bare "failed" with nothing the user could do.
    if app.status == ApplicationStatus.FAILED and app.resume_state:
        return verdict(
            NextAction.RESUME_APPLICATION,
            ApplicationHealth.BLOCKED,
            f"Paused at '{app.resume_state.get('current', 'unknown step')}' — resume it.",
            2.2,
            None,
            base_urgency=BLOCKING_URGENCY,
        )

    # 3b. A CAPTCHA/2FA wall stopped the run mid-apply. Recoverable, and the fastest path
    #     through is the browser window that hit it, not a fresh review — see
    #     workers.tasks._mark_needs_verification, which sets this resume_state marker.
    if (
        app.status == ApplicationStatus.PENDING_REVIEW
        and app.resume_state
        and app.resume_state.get("blocked_reason") == "captcha"
    ):
        return verdict(
            NextAction.COMPLETE_VERIFICATION,
            ApplicationHealth.BLOCKED,
            "A verification challenge is blocking this application — complete it in the "
            "browser window that opened for it, then resume.",
            2.2,
            None,
            base_urgency=BLOCKING_URGENCY,
        )

    # 4. A session went stale mid-flight: reconnect, then resume from the saved position.
    if app.paused_at and app.status == ApplicationStatus.APPLYING:
        idle = _days_since(app.paused_at, now) or 0
        if idle * 24 >= PAUSED_STALE_HOURS:
            return verdict(
                NextAction.RELOGIN,
                ApplicationHealth.SESSION_REQUIRED,
                f"Paused {_humanise(idle * -24)} ago — session likely expired. "
                "Reconnect to resume.",
                2.2,
                None,
                base_urgency=BLOCKING_URGENCY,
            )

    # 5. Waiting on the user's own approval. Cheap to clear, and blocks everything after it.
    if app.status == ApplicationStatus.PENDING_REVIEW:
        return verdict(
            NextAction.REVIEW_APPLICATION,
            ApplicationHealth.ACTION_REQUIRED,
            "Ready for your review before it is submitted.",
            1.6,
            None,
            base_urgency=BLOCKING_URGENCY,
        )

    # 6. Submitted but never confirmed — we do not actually know it landed.
    if app.status == ApplicationStatus.APPLIED and app.health == ApplicationHealth.STATUS_UNKNOWN:
        return verdict(
            NextAction.VERIFY_SUBMISSION,
            ApplicationHealth.STATUS_UNKNOWN,
            "Submission could not be confirmed — verify it was received.",
            1.5,
            None,
            base_urgency=BLOCKING_URGENCY,
        )

    # 7. Silence after submission. Worth one nudge, then leave it alone.
    if app.status == ApplicationStatus.APPLIED:
        age = _days_since(app.applied_at or app.created_at, now) or 0
        if age >= STALE_AFTER_DAYS:
            return verdict(
                NextAction.WAIT,
                ApplicationHealth.STALE,
                f"No response in {int(age)} days — likely closed.",
                0.4,
                None,
            )
        if age >= FOLLOW_UP_AFTER_DAYS:
            return verdict(
                NextAction.FOLLOW_UP,
                ApplicationHealth.NEEDS_ATTENTION,
                f"Submitted {int(age)} days ago with no reply — follow up.",
                1.2,
                app.follow_up_due_at,
            )
        return verdict(
            NextAction.WAIT,
            ApplicationHealth.HEALTHY,
            f"Submitted {int(age)} days ago — too early to chase.",
            0.3,
            None,
        )

    # 8. Queued for automation with no CV chosen: it cannot proceed as-is.
    if app.status in (ApplicationStatus.QUEUED, ApplicationStatus.APPROVED) and not (
        app.resume_id or app.document_version_id
    ):
        return verdict(
            NextAction.UPLOAD_CV,
            ApplicationHealth.DOCUMENT_REQUIRED,
            "No CV selected — choose one before this can be submitted.",
            2.0,
            None,
            base_urgency=BLOCKING_URGENCY,
        )

    # 9. Terminal states need nothing.
    if app.status in _TERMINAL:
        return ActionVerdict(
            NextAction.NONE,
            ApplicationHealth.HEALTHY,
            f"Closed ({app.status.value}).",
            0.0,
            ActionPriority.NONE,
        )

    return verdict(NextAction.WAIT, ApplicationHealth.HEALTHY, "In progress.", 0.3, None)


_TERMINAL = frozenset(
    {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN, ApplicationStatus.OFFER}
)


def _humanise(hours: float | None) -> str:
    """Render a duration the way a person would say it."""
    if hours is None:
        return "an unknown time"
    hours = abs(hours)
    if hours < 1:
        return f"{int(hours * 60)} minutes"
    if hours < 48:
        return f"{int(hours)} hours"
    return f"{int(hours / 24)} days"


def apply_verdict(app: Application, verdict: ActionVerdict) -> bool:
    """Write a verdict onto the application. Returns True if anything changed.

    Returning a change flag lets callers avoid writing a timeline event (and a WebSocket
    push) for a recomputation that produced the same answer — otherwise every scheduled
    sweep would spam the user's timeline with identical entries.
    """
    changed = (
        app.next_action != verdict.action
        or app.health != verdict.health
        or app.next_action_reason != verdict.reason
    )
    app.next_action = verdict.action
    app.health = verdict.health
    app.next_action_reason = verdict.reason
    app.next_action_score = verdict.score
    app.next_action_priority = verdict.priority
    app.action_due_at = verdict.due_at
    return changed
