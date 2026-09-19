"""Application-confirmation email notifications via the Gmail API.

Fires once, best-effort, when an application's status becomes APPLIED — from either the
automated apply pipeline (``workers.tasks``) or a manual status update
(``services.application.update_status``). Never raises to the caller: a notification email
failing must not fail the application itself, which is why every entry point here returns a
bool and swallows its own exceptions after logging them.

Requires the ``gmail.send`` scope (see ``services.gmail_auth``). A token issued before that
scope was added raises Google's insufficient-scope 403, which this treats the same as
"Gmail not connected" — the operator sees no email rather than a broken apply run, and the
Settings > Communications panel is where they'd notice and reconnect.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import gmail_auth

logger = structlog.get_logger(__name__)

_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_TIMEOUT = 15.0


def _build_raw_message(*, to: str, subject: str, body: str) -> str:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    # Gmail's send API takes the whole RFC 2822 message as one base64url blob — it fills in
    # `From` itself from the authenticated account, so this never has to know or claim an
    # address on the operator's behalf.
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


async def send_application_confirmation(
    db: AsyncSession, user_id: str, *, job_title: str, company: str, platform: str,
) -> bool:
    """Send the operator a one-line confirmation that an application went out.

    Returns whether an email was actually sent — False for every "nothing to do" case
    (Gmail never connected, scope not granted yet, transient API error) as well as genuine
    failures, all logged with enough detail to tell them apart, never raised.
    """
    if not gmail_auth.is_configured():
        return False
    if not await gmail_auth.is_connected(db, user_id):
        return False

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        return False

    try:
        token = await gmail_auth.get_valid_access_token(db, user_id)
    except gmail_auth.GmailNotConnectedError:
        return False

    subject = f"Applied: {job_title} at {company}"
    body = (
        f"Your CVil-War agent just submitted an application.\n\n"
        f"Role: {job_title}\n"
        f"Company: {company}\n"
        f"Platform: {platform}\n\n"
        "You can review the full run, including the submission evidence, in the app under "
        "Applications."
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
            # Insufficient scope on a token connected before gmail.send existed — a real,
            # expected state until the operator reconnects, not a bug to alarm on.
            logger.info(
                "gmail_send.insufficient_scope", user_id=user_id,
                detail="Reconnect Gmail to grant the send scope.",
            )
            return False
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("gmail_send.failed", user_id=user_id, error=str(exc))
        return False

    logger.info("gmail_send.application_confirmation_sent", user_id=user_id)
    return True
