"""A human approval that sticks.

The policy gate's ESCALATE verdict means "a person should look at this before it goes out"
(first run on a portal, a match below the threshold, a salary above the review line). Once the
operator has looked and pressed Approve, that condition is met. The worker used to re-run the
gate after approval, get the same ESCALATE, and put the application straight back into Needs
action — so approving never sent anything, and the operator had no way to proceed.

The approval is recorded on the application itself (``resume_state["approved_at"]``) so it
survives a policy HOLD re-queue (the run window), a worker restart, or a retry. It waives
ESCALATE only: a BLOCK (blocked employer, explicit no-sponsorship) and a HOLD (outside the run
window, daily cap) still apply, because those are rules the operator set, not questions they
were asked.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.application import Application

APPROVED_AT = "approved_at"


def mark_approved(app: Application, *, now: datetime | None = None) -> None:
    """Record that the operator approved this application for submission."""
    stamp = (now or datetime.now(UTC)).isoformat()
    retry_headed_after_verification(app)
    # Reassigned, not mutated in place: a JSON column only tracks assignment.
    app.resume_state = {**(app.resume_state or {}), APPROVED_AT: stamp}


def retry_headed_after_verification(app: Application) -> None:
    """A run stopped at a CAPTCHA/identity check: the next attempt opens a visible window on
    the automation host so the owner can clear the check, and the pause marker is cleared.

    Without this, approving a paused row re-ran it headless and hit the same wall every time,
    and the only resume control lived in a pop-up production never triggers.
    """
    state = dict(app.resume_state or {})
    if state.pop("blocked_reason", None) is not None:
        state["force_headed"] = True
    app.resume_state = state


def blocked_reason(app: Application) -> str | None:
    """Why a run paused for the owner (``captcha``), or ``None``."""
    return (app.resume_state or {}).get("blocked_reason") or None


def human_approved(app: Application) -> bool:
    """True once the operator has approved this application."""
    return bool((app.resume_state or {}).get(APPROVED_AT))
