"""Mandatory pre-submit confirmation: the agent stops and waits for the operator's explicit
go-ahead before the one truly irreversible step of a run — clicking the final submit control.

Built for a specific, real risk the operator raised: many UK employers refuse to accept a
second application from the same candidate for months after a rejection. A form the agent
filled in wrong and submitted unattended cannot be taken back. This is not a hard technical
guarantee against a browser-driving LLM ever clicking a submit button on its own initiative —
no prompt-based instruction to an LLM agent is — it is the strongest checkpoint available on
top of one, combined with running headed (``AutomationPolicy.run_headed``) so the operator can
watch the real, visible browser window at every step regardless of whether the agent calls
this tool correctly.

Two things make the checkpoint as solid as browser-use's own API allows:

* ``terminates_sequence=True`` on the registered action — even if the LLM batches this call
  together with a same-step submit click, nothing later in that batch runs once this one has
  returned or raised.
* On rejection or timeout, the shared :class:`ConfirmationOutcome` is set and read by a
  ``register_should_stop_callback`` passed into the ``Agent`` — this is browser-use's own
  documented mechanism for actually halting a run (``_check_stop_or_pause`` raises
  ``InterruptedError``), not a per-action failure the LLM could reason its way around in a
  later step.

Reuses the exact CAPTCHA/2FA rendezvous already built for intervention
(``core.automation.intervention``): same Redis BLPOP/RPUSH keyed on the application id, just a
different meaning for the response string (``"approved"`` vs. a typed 2FA code).
"""

import base64
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.api.websocket.bus import publish_progress
from app.core.automation.intervention import needs_intervention_event, request_intervention

logger = structlog.get_logger(__name__)

#: How long a run waits for the operator to approve or reject. Generous — they may be away
#: from the screen at the exact moment the agent reaches this point — but bounded, so a run
#: can never hang forever if nobody answers.
CONFIRMATION_TIMEOUT_SECONDS = 900


class SubmissionNotApprovedError(Exception):
    """The operator rejected the submission, or never responded in time.

    Distinct from ``HumanVerificationRequiredError``: this is not a technical blocker the
    agent hit, it is a deliberate human decision (or the deliberate absence of one) not to
    submit — worth recording as a different, honest reason on the application's timeline.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ConfirmationOutcome:
    """Shared between the registered action and the stop-callback below — the only channel
    connecting "the operator said no" to "actually stop this multi-step run"."""

    rejected: bool = False
    reason: str = ""


class SubmissionApprovalParams(BaseModel):
    summary: str = Field(
        description=(
            "One or two sentences describing exactly what you are about to submit: the job "
            "title, the company, and anything notable you filled in or answered on the form."
        )
    )


def build_confirmation_tools(
    *,
    redis: Redis | None,
    user_id: str,
    application_id: str,
    company: str,
    outcome: ConfirmationOutcome,
) -> Any:
    """A ``Tools`` instance with one action, ``request_submission_approval``.

    Built fresh per run (not a module-level singleton) because it closes over this specific
    application's id and its own ``outcome`` — the same reason ``build_apply_agent`` is called
    fresh per run rather than cached.
    """
    from browser_use import Tools
    from browser_use.agent.views import ActionResult
    from browser_use.browser.session import BrowserSession

    tools = Tools()

    @tools.registry.action(
        description=(
            "Call this immediately before clicking the final Submit/Apply/Confirm control on "
            "the application form — and ONLY once the form is completely filled in and you "
            "are ready to send it. This is mandatory: never click a final submission control "
            "without calling this first, and call nothing else in the same step as this "
            "action. It waits for the operator's explicit approval. If they reject it, or do "
            "not respond, the application ends here — do not attempt to submit by any other "
            "means afterward."
        ),
        param_model=SubmissionApprovalParams,
        terminates_sequence=True,
    )
    async def request_submission_approval(
        params: SubmissionApprovalParams, browser_session: BrowserSession
    ) -> ActionResult:
        url = await browser_session.get_current_page_url()
        screenshot_b64 = ""
        try:
            screenshot_bytes = await browser_session.take_screenshot()
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
        except Exception as exc:  # a failed screenshot must not block the confirmation itself
            logger.warning("submission_approval.screenshot_failed", error=str(exc))

        event = needs_intervention_event(
            application_id, "submit_confirmation",
            f"Ready to submit to {company or 'this employer'}: {params.summary}",
            url=url, screenshot_b64=screenshot_b64,
        )
        if redis is None:
            # No pub/sub, and nothing to rendezvous through — fail closed rather than
            # submitting unattended just because the channel to ask wasn't available.
            outcome.rejected = True
            outcome.reason = "No live connection was available to request approval through."
            return ActionResult(error=outcome.reason)

        try:
            await publish_progress(redis, user_id, event)
        except Exception as exc:
            logger.warning("submission_approval.publish_failed", error=str(exc))

        response = await request_intervention(
            redis, application_id, timeout=CONFIRMATION_TIMEOUT_SECONDS
        )
        if response is None:
            outcome.rejected = True
            outcome.reason = f"No response within {CONFIRMATION_TIMEOUT_SECONDS // 60} minutes."
            return ActionResult(error=outcome.reason)
        if response.strip().lower() != "approved":
            outcome.rejected = True
            outcome.reason = "The operator did not approve this submission."
            return ActionResult(error=outcome.reason)

        return ActionResult(
            extracted_content="Approved by the operator — proceed to submit now.",
            long_term_memory="Submission approved by the operator.",
        )

    return tools


def make_should_stop_callback(outcome: ConfirmationOutcome) -> Any:
    """The ``register_should_stop_callback`` passed to the ``Agent`` — checked by browser-use
    at every step boundary (``Agent._check_stop_or_pause``), which raises ``InterruptedError``
    the moment this returns ``True``. This is what turns "the operator said no" into the run
    actually ending, rather than the LLM being merely told one action failed and left free to
    try something else next."""

    async def _should_stop() -> bool:
        return outcome.rejected

    return _should_stop
