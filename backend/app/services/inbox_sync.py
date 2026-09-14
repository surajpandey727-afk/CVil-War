"""Gmail inbound reply detection, matched against applications and classified best-effort.

One sync cycle: fetch recent inbox messages, skip ones already seen (the unique constraint on
``communication_events`` is the real guard; an in-memory check here just avoids the wasted
Gmail API calls), match each to an application by sender-vs-employer name, classify a match's
likely content (rejection / interview invite / just a reply), and write the result — onto the
matched application's own timeline when confident, or into ``communication_events`` for the
operator to confirm when not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.comms.classify import classify
from app.core.job_discovery.dedup import companies_match
from app.core.orchestration.recorder import record_agent_run
from app.db.session import async_session_factory
from app.db.tenant import current_user_id
from app.models.application import Application
from app.models.communication_event import CommunicationEvent
from app.models.enums import AgentName, ApplicationEventType
from app.models.job import Job
from app.models.user import User
from app.services import gmail_auth
from app.services.timeline import record_event

logger = structlog.get_logger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TIMEOUT = 20.0
#: Bounded like every other external sync in this codebase (Tarve's page cap, Apollo's
#: contact-per-call limit) — a personal inbox sync needs recent mail, not the full archive.
_DEFAULT_MAX_RESULTS = 30
_DEFAULT_QUERY = "newer_than:30d in:inbox -category:promotions -category:social"

_EVENT_TYPE_FOR_CLASSIFICATION: dict[str, ApplicationEventType] = {
    "rejection": ApplicationEventType.EMAIL_REJECTION_DETECTED,
    "interview_invite": ApplicationEventType.EMAIL_INTERVIEW_INVITE_DETECTED,
    "reply": ApplicationEventType.EMAIL_REPLY_RECEIVED,
}


@dataclass(frozen=True)
class InboxSyncResult:
    fetched: int
    already_seen: int
    matched_to_application: int
    unmatched: int
    errors: list[str] = field(default_factory=list)


async def _fetch_message_ids(
    client: httpx.AsyncClient, token: str, query: str, limit: int
) -> list[str]:
    response = await client.get(
        f"{_GMAIL_API}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": query, "maxResults": limit},
    )
    response.raise_for_status()
    return [m["id"] for m in response.json().get("messages", [])]


def _header(headers: list[dict[str, str]], name: str) -> str:
    return next(
        (h["value"] for h in headers if h.get("name", "").casefold() == name.casefold()), ""
    )


async def _fetch_message(client: httpx.AsyncClient, token: str, message_id: str) -> dict:
    response = await client.get(
        f"{_GMAIL_API}/messages/{message_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "format": "metadata",
            "metadataHeaders": ["Subject", "From"],
        },
    )
    response.raise_for_status()
    body = response.json()
    headers = body.get("payload", {}).get("headers", [])
    occurred_at = datetime.fromtimestamp(
        int(body["internalDate"]) / 1000, tz=UTC
    ) if body.get("internalDate") else datetime.now(UTC)
    return {
        "id": body["id"],
        "sender": _header(headers, "From"),
        "subject": _header(headers, "Subject"),
        "snippet": body.get("snippet", ""),
        "occurred_at": occurred_at,
    }


def _sender_company_hint(sender: str) -> str:
    """A best-guess employer name from a ``From`` header, for matching against ``Job.company``.

    Prefers the display name ("Monzo Recruiting" from ``"Monzo Recruiting" <x@monzo.com>``)
    since it is usually the actual company name; falls back to the email domain's own label
    (``monzo`` from ``x@monzo.com``) when there is no display name, which covers plain
    ``noreply@monzo.com``-style senders.
    """
    sender = sender.strip()
    if "<" in sender:
        display, _, addr = sender.partition("<")
        display = display.strip().strip('"')
        if display:
            return display
        sender = addr.rstrip(">")
    domain = sender.rsplit("@", 1)[-1]
    return domain.split(".")[0] if domain else ""


async def _load_candidate_applications(
    db: AsyncSession, user_id: str
) -> list[tuple[Application, str]]:
    """Every application this user has actually submitted, with its employer name.

    Restricted to applications with a real ``applied_at`` — a reply about a job never applied
    to cannot exist, and including queued/draft rows would only invite false matches.
    """
    rows = (
        await db.execute(
            select(Application, Job)
            .join(Job, Job.id == Application.job_id)
            .where(Application.user_id == user_id, Application.applied_at.isnot(None))
        )
    ).all()
    return [(app, job.company) for app, job in rows]


def _match_application(
    sender: str, candidates: list[tuple[Application, str]]
) -> Application | None:
    hint = _sender_company_hint(sender)
    if not hint:
        return None
    matches = [app for app, company in candidates if company and companies_match(hint, company)]
    # More than one application at the same employer is genuinely ambiguous (which role does
    # this reply concern?) — leaving it unmatched for the operator to confirm beats guessing
    # which one, which could attach a rejection to the wrong application.
    return matches[0] if len(matches) == 1 else None


async def sync_inbox(
    db: AsyncSession,
    user_id: str,
    *,
    query: str = _DEFAULT_QUERY,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> InboxSyncResult:
    """Run one Gmail sync cycle for this user. Raises ``gmail_auth.GmailNotConnectedError``
    if Gmail has never been connected — the caller (endpoint) turns that into a clear
    "connect Gmail first" response rather than a generic 500."""
    token = await gmail_auth.get_valid_access_token(db, user_id)
    candidates = await _load_candidate_applications(db, user_id)

    already_seen = matched = unmatched = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        message_ids = await _fetch_message_ids(client, token, query, max_results)
        for message_id in message_ids:
            existing = (
                await db.execute(
                    select(CommunicationEvent).where(
                        CommunicationEvent.user_id == user_id,
                        CommunicationEvent.source == "gmail",
                        CommunicationEvent.external_id == message_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                already_seen += 1
                continue
            try:
                msg = await _fetch_message(client, token, message_id)
            except Exception as exc:  # one bad message must not abort the whole sync
                errors.append(f"{message_id}: {exc}")
                continue

            classification = classify(msg["subject"], msg["snippet"])
            app = _match_application(msg["sender"], candidates)

            if app is not None:
                await record_event(
                    db, app, _EVENT_TYPE_FOR_CLASSIFICATION[classification],
                    f"Email reply detected: {msg['subject'][:200] or '(no subject)'}",
                    detail=msg["snippet"][:500],
                    payload={"sender": msg["sender"], "gmail_message_id": message_id},
                    actor="system", occurred_at=msg["occurred_at"],
                )
                db.add(CommunicationEvent(
                    user_id=user_id, source="gmail", external_id=message_id,
                    application_id=app.id, sender=msg["sender"][:300], subject=msg["subject"][:500],
                    snippet=msg["snippet"][:2000], occurred_at=msg["occurred_at"],
                    matched_confidence=1.0, classified_as=classification,
                ))
                matched += 1
            else:
                db.add(CommunicationEvent(
                    user_id=user_id, source="gmail", external_id=message_id,
                    application_id=None, sender=msg["sender"][:300], subject=msg["subject"][:500],
                    snippet=msg["snippet"][:2000], occurred_at=msg["occurred_at"],
                    matched_confidence=0.0, classified_as=classification,
                ))
                unmatched += 1

    await db.commit()
    logger.info(
        "inbox_sync.complete", user_id=user_id, fetched=len(message_ids),
        matched=matched, unmatched=unmatched, already_seen=already_seen, errors=len(errors),
    )
    return InboxSyncResult(
        fetched=len(message_ids), already_seen=already_seen,
        matched_to_application=matched, unmatched=unmatched, errors=errors,
    )


async def run_inbox_sync_for_all_users(ctx: dict) -> None:
    """Scheduled (Arq cron) and on-demand (internal webhook) fan-out: sync every active
    user who has actually connected Gmail — the Tracking agent's real trigger point.

    Mirrors ``discovery_scheduler.run_discovery_for_all_users`` exactly: tenant-scope per
    user for the duration of their own sync, never let one user's failure (or a Gmail auth
    error) stop the rest of the cycle, and record every attempt as a real ``AgentRun`` row
    rather than a log line only the operator running this process can see.
    """
    redis = ctx.get("redis")
    async with async_session_factory() as db:
        user_ids = (
            await db.execute(
                select(User.id).where(User.is_active.is_(True), User.deleted_at.is_(None))
            )
        ).scalars().all()

        synced = 0
        for user_id in user_ids:
            token = current_user_id.set(user_id)
            try:
                if not await gmail_auth.is_connected(db, user_id):
                    continue
                async with record_agent_run(
                    db, user_id, AgentName.TRACKING,
                    input_summary="Sync Gmail for reply detection",
                    linked_entity_type="user", linked_entity_id=user_id, redis=redis,
                ) as run:
                    result = await sync_inbox(db, user_id)
                    run.output_summary = (
                        f"{result.matched_to_application} matched, {result.unmatched} unmatched"
                    )
                synced += 1
            except Exception as exc:
                logger.error("inbox_sync.user_run_failed", user_id=user_id, error=str(exc))
            finally:
                current_user_id.reset(token)

    logger.info("inbox_sync.cycle_complete", users_checked=len(user_ids), users_synced=synced)
