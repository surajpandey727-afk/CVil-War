"""Application-confirmation email notifications via the Gmail API.

Fires once, best-effort, when an application's status becomes APPLIED — from either the
automated apply pipeline (``workers.tasks``) or a manual status update
(``services.application.update_status``). Never raises to the caller: a notification email
failing must not fail the application itself.

Two things this module is careful about, because both were silent holes the operator could not
see past:

* **Honesty.** The email's wording follows the application's :class:`ConfirmationState`. A run
  that only *simulated* a submission (``BROWSER__LIVE_APPLY`` off) sends no "you applied" email
  at all — claiming an application went out when nothing was sent is exactly the false success
  the confirmation state exists to prevent. An *unconfirmed* submission says so plainly.
* **Observability.** Every attempt records its outcome on the application's own timeline
  (:func:`notify_application_submitted`), so "did the confirmation email fire, and if not why"
  is answerable from the application's history instead of living only in a swallowed exception.
  The bare :func:`send_application_confirmation` still just sends and returns the outcome, for
  callers (and tests) that do their own recording.

Requires the ``gmail.send`` scope (see ``services.gmail_auth``). A token issued before that
scope was added raises Google's insufficient-scope 403, reported as its own outcome rather than
a generic failure — the Settings > Communications panel is where the operator reconnects.
"""

from __future__ import annotations

import base64
import contextlib
from email.message import EmailMessage
from enum import StrEnum

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.enums import ApplicationEventType, ConfirmationState
from app.models.user import User
from app.services import gmail_auth

logger = structlog.get_logger(__name__)

_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_TIMEOUT = 15.0


class NotifyOutcome(StrEnum):
    """What became of a confirmation-email attempt — recorded so it is never a silent no-op."""

    SENT = "sent"
    #: No Google OAuth client is set up at all (GMAIL_CLIENT_ID/SECRET unset).
    NOT_CONFIGURED = "not_configured"
    #: The client is configured but this operator never completed the consent flow.
    NOT_CONNECTED = "not_connected"
    #: The stored token predates the ``gmail.send`` scope — reconnect to grant it.
    INSUFFICIENT_SCOPE = "insufficient_scope"
    #: A transient Gmail API / network error.
    FAILED = "failed"
    #: The run only simulated a submission, so no "you applied" email was sent, by design.
    SKIPPED_SIMULATED = "skipped_simulated"


#: Outcomes that mean the operator is in the dark about an otherwise-successful application and
#: would benefit from a nudge to connect Gmail.
NOT_DELIVERED = frozenset(
    {NotifyOutcome.NOT_CONFIGURED, NotifyOutcome.NOT_CONNECTED, NotifyOutcome.INSUFFICIENT_SCOPE}
)


def _build_raw_message(*, to: str, subject: str, body: str) -> str:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    # Gmail's send API takes the whole RFC 2822 message as one base64url blob — it fills in
    # `From` itself from the authenticated account, so this never has to know or claim an
    # address on the operator's behalf.
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _compose(
    *, job_title: str, company: str, platform: str,
    confirmation_state: ConfirmationState, reference: str = "",
) -> tuple[str, str]:
    """Subject and body for an applied notification, worded for the confirmation state.

    An *unconfirmed* submission must not read like a confirmed one: the whole point of the state
    is that the agent finished the steps but the portal never acknowledged it, so the email asks
    the operator to verify rather than telling them it is done.
    """
    role_line = f"Role: {job_title}\nCompany: {company}\nPlatform: {platform}\n"
    if confirmation_state is ConfirmationState.CONFIRMED:
        subject = f"Applied: {job_title} at {company}"
        ref_line = f"Reference: {reference}\n" if reference else ""
        body = (
            "Your CVil-War agent submitted an application and the portal acknowledged it.\n\n"
            f"{role_line}{ref_line}\n"
            "You can review the full run, including the submission evidence, in the app under "
            "Applications."
        )
    else:  # UNCONFIRMED — sent, but nothing corroborated it
        subject = f"Submitted (please verify): {job_title} at {company}"
        body = (
            "Your CVil-War agent completed the submission steps, but the portal did not return a "
            "confirmation, so this one is worth verifying yourself.\n\n"
            f"{role_line}\n"
            "Open the application in CVil-War to see the submission evidence and confirm it "
            "landed."
        )
    return subject, body


async def send_application_confirmation(
    db: AsyncSession, user_id: str, *, job_title: str, company: str, platform: str,
    confirmation_state: ConfirmationState = ConfirmationState.CONFIRMED,
) -> NotifyOutcome:
    """Send the operator a confirmation that an application went out, worded for its state.

    Returns a :class:`NotifyOutcome` describing exactly what happened — the caller (or
    :func:`notify_application_submitted`) records it. Never raises.
    """
    if confirmation_state in (ConfirmationState.SIMULATED, ConfirmationState.PENDING,
                              ConfirmationState.FAILED):
        # Nothing actually reached an employer; a "you applied" email would be a false claim.
        return NotifyOutcome.SKIPPED_SIMULATED
    if not gmail_auth.is_configured():
        return NotifyOutcome.NOT_CONFIGURED
    if not await gmail_auth.is_connected(db, user_id):
        return NotifyOutcome.NOT_CONNECTED

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        return NotifyOutcome.NOT_CONNECTED

    try:
        token = await gmail_auth.get_valid_access_token(db, user_id)
    except gmail_auth.GmailNotConnectedError:
        return NotifyOutcome.NOT_CONNECTED

    subject, body = _compose(
        job_title=job_title, company=company, platform=platform,
        confirmation_state=confirmation_state,
    )
    raw = _build_raw_message(to=user.email, subject=subject, body=body)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _SEND_URL,
                headers={"Authorization": f"Bearer {token}"},
                json={"raw": raw},
            )
        if response.status_code == 403:
            logger.info(
                "gmail_send.insufficient_scope", user_id=user_id,
                detail="Reconnect Gmail to grant the send scope.",
            )
            return NotifyOutcome.INSUFFICIENT_SCOPE
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("gmail_send.failed", user_id=user_id, error=str(exc))
        return NotifyOutcome.FAILED

    logger.info("gmail_send.application_confirmation_sent", user_id=user_id)
    return NotifyOutcome.SENT


async def send_test_email(db: AsyncSession, user_id: str) -> NotifyOutcome:
    """Send a one-off test message from the connected account to itself, to prove it works.

    Returns the outcome so the caller can show the operator exactly what happened. Never raises.
    The recipient is the authenticated account's own address, so "verify in your inbox" means
    checking the same mailbox CVil-War will send future notifications to.
    """
    if not gmail_auth.is_configured():
        return NotifyOutcome.NOT_CONFIGURED
    if not await gmail_auth.is_connected(db, user_id):
        return NotifyOutcome.NOT_CONNECTED
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        return NotifyOutcome.NOT_CONNECTED
    try:
        token = await gmail_auth.get_valid_access_token(db, user_id)
    except gmail_auth.GmailNotConnectedError:
        return NotifyOutcome.NOT_CONNECTED

    raw = _build_raw_message(
        to=user.email,
        subject="CVil-War: email notifications are working",
        body=(
            "This is a test from CVil-War.\n\n"
            "Your Gmail is connected, and application-confirmation emails will arrive here when "
            "your applications go out. You can disconnect any time under Communications.\n\n"
            "— CVil-War"
        ),
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _SEND_URL, headers={"Authorization": f"Bearer {token}"}, json={"raw": raw}
            )
        if response.status_code == 403:
            return NotifyOutcome.INSUFFICIENT_SCOPE
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("gmail_send.test_failed", user_id=user_id, error=str(exc))
        return NotifyOutcome.FAILED
    logger.info("gmail_send.test_sent", user_id=user_id)
    return NotifyOutcome.SENT


_TIMELINE_NOTE: dict[NotifyOutcome, str] = {
    NotifyOutcome.SENT: "Confirmation email sent.",
    NotifyOutcome.NOT_CONFIGURED: (
        "No confirmation email: Gmail notifications are not set up on this deployment."
    ),
    NotifyOutcome.NOT_CONNECTED: (
        "No confirmation email: Gmail is not connected. Connect it under "
        "Communications to be notified when applications go out."
    ),
    NotifyOutcome.INSUFFICIENT_SCOPE: (
        "No confirmation email: Gmail is connected but missing the send permission. "
        "Reconnect Gmail under Communications to grant it."
    ),
    NotifyOutcome.FAILED: "Confirmation email could not be sent (a Gmail API error); the "
    "application itself is unaffected.",
    NotifyOutcome.SKIPPED_SIMULATED: (
        "No confirmation email: this run only simulated a submission, so nothing was sent to "
        "the employer."
    ),
}


async def notify_application_submitted(
    db: AsyncSession, app: Application, *, job_title: str, company: str, platform: str,
) -> NotifyOutcome:
    """Send the confirmation email for ``app`` and record the outcome on its timeline.

    Fully self-contained and exception-safe: sends worded for ``app.confirmation_state``, writes
    one timeline entry naming what happened (so "why didn't I get an email" is answerable from
    the application's own history), commits that entry, and returns the outcome. A failure
    anywhere here never propagates — the application has already been committed as APPLIED by the
    caller and must not be undone by a notification problem.
    """
    outcome = NotifyOutcome.FAILED
    try:
        outcome = await send_application_confirmation(
            db, app.user_id, job_title=job_title, company=company, platform=platform,
            confirmation_state=app.confirmation_state,
        )
    except Exception as exc:  # defensive: send already swallows, this is belt-and-braces
        logger.warning("gmail_send.notify_unexpected_error", application_id=app.id, error=str(exc))
    with contextlib.suppress(Exception):
        from app.services.timeline import record_event

        await record_event(
            db, app, ApplicationEventType.NOTE_ADDED,
            _TIMELINE_NOTE.get(outcome, "Confirmation email outcome unknown."),
            payload={"notification": outcome.value},
            actor="system",
            recompute=False,
        )
        await db.commit()
    return outcome
