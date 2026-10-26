"""In-app notifications, and their email copy through the operator's own Gmail.

Three producers feed this, each at the one place its fact already becomes true:

* ``timeline.record_event`` — every application state change (submitted, failed, needs you,
  interview, recruiter reply, rejection) already passes through it, so hooking there means no
  path can change an application without the user hearing about it.
* ``job_search.search_jobs`` — after new UK jobs are stored: one "N new jobs" notification and
  one per strong match, scored by the résumé checker's deterministic engine against the user's
  latest base résumé.
* Anything else can call :func:`notify` directly.

Emitting never raises into the caller (a notification must not fail an application or a
search) and is idempotent per ``dedup_key``. Email goes out only for the kinds worth an
interruption, only when Gmail is connected, and never for the application-submitted case —
``gmail_send.notify_application_submitted`` already sends that one, worded for its
confirmation state.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.enums import ApplicationEventType, ConfirmationState
from app.models.job import Job
from app.models.notification import Notification

logger = structlog.get_logger(__name__)

#: Kinds that are worth an email as well as the in-app bell.
EMAIL_KINDS = frozenset(
    {"best_match", "action_required", "application_failed", "interview", "recruiter_reply"}
)
#: A new job at or above this deterministic fit (0-1) is announced as a best match.
BEST_MATCH_FLOOR = 0.70
MAX_BEST_MATCHES_PER_SEARCH = 3


async def notify(
    db: AsyncSession,
    user_id: str,
    *,
    kind: str,
    title: str,
    dedup_key: str,
    body: str | None = None,
    link: str | None = None,
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: str | None = None,
    email: bool | None = None,
) -> Notification | None:
    """Record one notification (idempotent on ``dedup_key``); optionally email it.

    Uses a SAVEPOINT so a duplicate insert rolls back only itself, never the caller's
    transaction. Returns the new row, or ``None`` for a duplicate or a failure.
    """
    row = Notification(
        user_id=user_id,
        kind=kind,
        severity=severity,
        title=title[:200],
        body=body,
        link=link,
        entity_type=entity_type,
        entity_id=entity_id,
        dedup_key=dedup_key[:160],
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return None
    except Exception as exc:
        logger.warning("notification_failed", kind=kind, error=str(exc)[:200])
        return None

    if email if email is not None else kind in EMAIL_KINDS:
        await _email(db, user_id, row)
    return row


async def _email(db: AsyncSession, user_id: str, row: Notification) -> None:
    from app.services.gmail_send import NotifyOutcome, send_notification_email

    try:
        outcome = await send_notification_email(
            db,
            user_id,
            subject=f"CVil-War: {row.title}",
            body=f"{row.body or row.title}\n\nOpen in CVil-War: {_absolute(row.link)}\n",
        )
    except Exception as exc:  # belt and braces — the sender is already non-raising
        logger.warning("notification_email_failed", error=str(exc)[:200])
        return
    if outcome is NotifyOutcome.SENT:
        row.emailed_at = datetime.now(UTC)


def _absolute(link: str | None) -> str:
    from app.config.settings import get_settings

    base = (get_settings().frontend_url or "https://cvil-war.vercel.app").rstrip("/")
    return f"{base}{link or '/'}"


# --- producers ----------------------------------------------------------------------------


_EVENT_KINDS: dict[ApplicationEventType, tuple[str, str]] = {
    ApplicationEventType.USER_ACTION_REQUIRED: ("action_required", "warning"),
    ApplicationEventType.ERROR: ("application_failed", "critical"),
    ApplicationEventType.INTERVIEW_SCHEDULED: ("interview", "success"),
    ApplicationEventType.ASSESSMENT_INVITED: ("interview", "success"),
    # Detected in the inbox: the most important email there is, and it used to produce no
    # notification at all.
    ApplicationEventType.EMAIL_INTERVIEW_INVITE_DETECTED: ("interview", "success"),
    ApplicationEventType.EMAIL_REPLY_RECEIVED: ("recruiter_reply", "info"),
    ApplicationEventType.EMAIL_REJECTION_DETECTED: ("rejection", "info"),
}


def _fingerprint(summary: str, payload: dict | None) -> str:
    """Short, stable identity for one occurrence: the message id when there is one."""
    import hashlib

    ident = (payload or {}).get("gmail_message_id") or summary or ""
    return hashlib.sha1(str(ident).encode()).hexdigest()[:12]


async def from_application_event(
    db: AsyncSession,
    app: Application,
    event_type: ApplicationEventType,
    summary: str,
    payload: dict | None,
) -> None:
    """Turn an application timeline event into a notification, when it is one worth having."""
    try:
        if event_type is ApplicationEventType.APPLICATION_SUBMITTED:
            kind, severity = "application_submitted", "success"
        elif event_type in _EVENT_KINDS:
            kind, severity = _EVENT_KINDS[event_type]
        else:
            return
        job = await db.get(Job, app.job_id) if app.job_id else None
        role = f"{job.title} at {job.company}" if job else "an application"
        title = {
            "application_submitted": f"Applied: {role}",
            "action_required": f"Needs you: {role}",
            "application_failed": f"Application failed: {role}",
            "interview": f"Interview step: {role}",
            "recruiter_reply": f"Recruiter reply: {role}",
            "rejection": f"Closed: {role}",
        }[kind]
        if kind == "application_submitted" and app.confirmation_state == (
            ConfirmationState.SIMULATED
        ):
            # Honesty over good news: a rehearsal never reads as a submission.
            title, severity = f"Rehearsal only (nothing sent): {role}", "info"
        action = (payload or {}).get("action", "")
        await notify(
            db,
            app.user_id,
            kind=kind,
            severity=severity,
            title=title,
            body=summary,
            link=f"/applications/{app.id}",
            entity_type="application",
            entity_id=app.id,
            # Keyed on what happened, not just its type: a second, different reason to need the
            # owner (a CAPTCHA after a policy question, a new failure after a re-run) used to
            # collide with the first and never notify. The same reason repeated still dedups.
            dedup_key=(
                f"{kind}:{app.id}:{action or event_type.value}:{_fingerprint(summary, payload)}"
            ),
        )
    except Exception as exc:
        logger.warning("notification_from_event_failed", error=str(exc)[:200])


async def notify_new_jobs(db: AsyncSession, user_id: str, new_jobs: list[Job]) -> int:
    """Announce newly stored UK jobs, and the strongest of them as best matches."""
    uk = [j for j in new_jobs if j.uk_eligible]
    if not uk:
        return 0
    try:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M")
        titles = ", ".join(f"{j.title} ({j.company})" for j in uk[:3])
        more = f" and {len(uk) - 3} more" if len(uk) > 3 else ""
        await notify(
            db,
            user_id,
            kind="new_jobs",
            title=f"{len(uk)} new UK job{'s' if len(uk) != 1 else ''} found",
            body=f"{titles}{more}.",
            link="/jobs",
            dedup_key=f"new_jobs:{stamp}:{len(uk)}",
        )
        matches = await _best_matches(db, user_id, uk)
        for job, score in matches:
            await notify(
                db,
                user_id,
                kind="best_match",
                severity="success",
                title=f"Strong match ({round(score * 100)}%): {job.title} at {job.company}",
                body=(
                    f"{job.title} at {job.company} scores {round(score * 100)}/100 against your "
                    "latest résumé. Open the Résumé checker to see the evidence and the gaps."
                ),
                link=f"/resume-checker?job={job.id}",
                entity_type="job",
                entity_id=job.id,
                dedup_key=f"best_match:{job.id}",
            )
        return 1 + len(matches)
    except Exception as exc:
        logger.warning("notify_new_jobs_failed", error=str(exc)[:200])
        return 0


async def _best_matches(db: AsyncSession, user_id: str, jobs: list[Job]) -> list[tuple[Job, float]]:
    """Deterministic fit of each job against the user's latest base résumé, strongest first."""
    from app.core.resume_check.check import CheckInput, build_check
    from app.core.resume_check.targets import job_target
    from app.models.resume import Resume
    from app.schemas.resume_check import CheckTarget

    resume = (
        await db.execute(
            select(Resume)
            .where(Resume.user_id == user_id, Resume.type == "base")
            .order_by(Resume.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    text = (resume.content_text if resume else "") or ""
    if len(text.split()) < 30:
        return []
    scored: list[tuple[Job, float]] = []
    for job in jobs:
        if len((job.description or "").split()) < 40:
            continue  # too thin to score honestly
        check, _ = build_check(
            CheckInput(
                resume_id=resume.id,
                resume_name=resume.name,
                resume_text=text,
                target=job_target(job.title or "", job.description or ""),
                target_info=CheckTarget(kind="job", job_id=job.id, title=job.title or ""),
                uk_demand={},
                uk_jobs_scanned=0,
            )
        )
        if check.score.overall >= BEST_MATCH_FLOOR:
            scored.append((job, check.score.overall))
    scored.sort(key=lambda js: -js[1])
    return scored[:MAX_BEST_MATCHES_PER_SEARCH]


# --- reads --------------------------------------------------------------------------------


async def list_for_user(
    db: AsyncSession, *, unread_only: bool = False, limit: int = 30
) -> list[Notification]:
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list((await db.execute(stmt)).scalars().all())


async def unread_count(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(Notification).where(Notification.read_at.is_(None))
        )
        or 0
    )


async def mark_read(db: AsyncSession, user_id: str, notification_id: str | None = None) -> int:
    """Mark one (or, with no id, every) unread notification as read. Returns rows changed."""
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    if notification_id:
        stmt = stmt.where(Notification.id == notification_id)
    result = await db.execute(stmt)
    await db.commit()
    return int(result.rowcount or 0)
