"""Everything needed to prove what happened to one application.

The product says ``Applied``. This module answers the follow-up: applied where, to which job,
using which CV, through which account, at what time, with what result, and what exactly did
the agent do. Every field here is read from a record the system already wrote — nothing is
derived optimistically, and nothing is invented when it is missing.

**Missing data is reported as missing.** A historical application created before the run
recorder existed has no method, no account and no logs. Those come back as ``None`` with an
explicit ``recorded=False`` on the section, so the UI can say "Not recorded" instead of
rendering a plausible blank that reads as fact.

Assembled from existing models rather than a new one:

* :class:`~app.models.job.Job` — title, employer, location, salary, board, URL
* :class:`~app.models.application.Application` — status, submission method, confirmation
* :class:`~app.models.resume.Resume` — the CV actually attached at submission
* :class:`~app.models.platform_session.PlatformSession` — which login, masked
* :class:`~app.models.application_event.ApplicationEvent` — the timeline the app already keeps
* :class:`~app.models.harness.RunTrajectory` / ``RunDiagnosis`` — the automation's own steps
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.application_event import ApplicationEvent
from app.models.enums import (
    ApplicationStatus,
    ConfirmationState,
    SessionState,
    SubmissionMethod,
)
from app.models.harness import RunDiagnosis, RunTrajectory, RunVerdict
from app.models.job import Job
from app.models.platform_session import PlatformSession
from app.models.resume import Resume
from app.schemas.evidence import (
    ApplicationEvidence,
    EvidenceAccount,
    EvidenceCoverLetter,
    EvidenceDocument,
    EvidenceFailure,
    EvidenceJob,
    EvidenceLogEntry,
    EvidenceSubmission,
)

logger = structlog.get_logger(__name__)

#: Statuses in which something was, or is being, sent to an employer.
_SENT = (
    ApplicationStatus.APPLYING,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.REJECTED,
    ApplicationStatus.OFFER,
)

_EMAIL = re.compile(r"^([^@]+)@(.+)$")

#: Session states in which the account can actually be used. An expiring session still works,
#: which is why it counts as connected — the connection centre nags about it separately.
#: Everything else (expired, MFA, blocked) means the submission did not go through a live
#: login, and reporting it as "connected" would send an operator looking in the wrong place.
_USABLE_SESSION_STATES = (SessionState.SESSION_ACTIVE, SessionState.SESSION_EXPIRING)


def mask_account(identifier: str | None) -> str | None:
    """Reduce an account identifier to something safe to display.

    ``suraj.pandey@example.com`` becomes ``sur***@example.com``: enough to tell two logins
    apart when debugging a portal, not enough to be a credential or to fully disclose the
    address in a screenshot. Anything that is not an email is truncated the same way rather
    than passed through, because an unrecognised format is not a licence to show all of it.
    """
    if not identifier:
        return None
    match = _EMAIL.match(identifier.strip())
    if match:
        local, domain = match.groups()
        head = local[:3] if len(local) > 3 else local[:1]
        return f"{head}***@{domain}"
    text = identifier.strip()
    return f"{text[:3]}***" if len(text) > 3 else "***"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _job_section(job: Job | None, app: Application) -> EvidenceJob:
    """The posting, and the two URLs that are not interchangeable.

    ``url`` is where the advert lives; ``application_url`` is where the form is. Assuming they
    are the same sends the operator to a listing page when they wanted the submission they
    made — so both are carried, and the absence of either is stated rather than papered over
    by falling back to the other.
    """
    if job is None:
        return EvidenceJob(recorded=False)
    return EvidenceJob(
        recorded=True,
        job_id=job.id,
        title=job.title or None,
        company=job.company or None,
        location=job.location or None,
        salary=job.salary_range or None,
        remote=bool(job.remote),
        source=app.portal or job.platform or None,
        job_url=job.url or None,
        # Only when it genuinely differs — repeating the job URL under a second heading
        # implies a separate application page that does not exist.
        application_url=(
            app.application_url
            if app.application_url and app.application_url != job.url
            else None
        ),
        posted_at=_aware(job.posted_date),
    )


def _submission_section(app: Application) -> EvidenceSubmission:
    """Status, method and whether anything actually confirmed it.

    The load-bearing distinction: ``Applying`` is in flight, ``Applied`` means the lifecycle
    reached submission, and ``confirmation_state`` says whether an employer's system
    acknowledged it. A run with live apply disabled reports ``simulated`` — it is not a
    submission and must never read as one.
    """
    method = app.submission_method
    return EvidenceSubmission(
        status=str(app.status),
        # `none` on a sent application means the row predates run recording, not that it was
        # sent by no method at all.
        method=str(method) if method != SubmissionMethod.NONE else None,
        confirmation_state=str(app.confirmation_state),
        confirmation_detail=app.confirmation_detail,
        external_reference=app.external_reference,
        submitted_at=_aware(app.applied_at),
        ats_score=app.ats_score,
        apply_mode=str(app.apply_mode),
        origin=app.origin,
        actor=(
            "agent"
            if method in (SubmissionMethod.AUTOMATED, SubmissionMethod.SIMULATED)
            else "you"
            if method == SubmissionMethod.MANUAL
            else None
        ),
        recorded=app.status in _SENT or app.confirmation_state != ConfirmationState.PENDING,
    )


def _resume_section(resume: Resume | None) -> EvidenceDocument:
    """The exact CV attached to this application.

    Résumé rows are effectively immutable — tailoring and optimising both create a new row
    rather than rewriting one (see ``services.resume.optimize_resume``) — so the reference is
    a genuine snapshot of what was sent, not a pointer at whatever the CV has since become.
    There is no separate version number to show, so the row's own identity and creation time
    are given instead of inventing a "v4".
    """
    if resume is None:
        return EvidenceDocument(recorded=False)
    return EvidenceDocument(
        recorded=True,
        document_id=resume.id,
        name=resume.name,
        kind=str(resume.type),
        ats_score=resume.ats_score,
        created_at=_aware(resume.created_at),
        archived=resume.archived_at is not None,
        has_pdf=bool(resume.file_path_pdf),
        has_docx=bool(resume.file_path_docx),
    )


def _cover_letter_section(app: Application) -> EvidenceCoverLetter:
    """Whether a letter went with it, and whether it was generated or chosen.

    Only the storage key is persisted today, so "generated" is inferred from where the file
    lives rather than asserted from a field that does not exist. Where that cannot be told,
    ``origin`` is left unset instead of guessing.
    """
    path = app.cover_letter_path
    if not path:
        return EvidenceCoverLetter(recorded=True, used=False)
    origin = "generated" if "/letters/" in path or "cover" in path.lower() else None
    return EvidenceCoverLetter(recorded=True, used=True, name=path.rsplit("/", 1)[-1],
                               origin=origin)


async def _account_section(db: AsyncSession, app: Application, platform: str | None
                           ) -> EvidenceAccount:
    """Which login was used, with nothing secret in it.

    The encrypted cookies and passwords live in ``user_credentials`` and are not read here at
    all. What comes back is the platform, a masked label and the connection state — the
    minimum needed to answer "which account did this go through" while debugging.
    """
    if not platform:
        return EvidenceAccount(recorded=False)
    session = (
        await db.execute(
            select(PlatformSession).where(
                PlatformSession.user_id == app.user_id,
                PlatformSession.platform == platform,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        return EvidenceAccount(
            recorded=True,
            platform=platform,
            connected=False,
            state="not_connected",
            detail="No connected account for this platform — the application did not sign in.",
        )
    return EvidenceAccount(
        recorded=True,
        platform=platform,
        # Already masked at write time; masked again on read so a row written before
        # `mask_account` existed cannot leak a full address through this endpoint.
        account=mask_account(session.account_label),
        connected=session.state in _USABLE_SESSION_STATES,
        state=str(session.state),
        detail=session.state_detail,
        last_used_at=_aware(session.last_used_at),
    )


async def _log_entries(db: AsyncSession, app: Application) -> list[EvidenceLogEntry]:
    """The real execution history, from the two recorders that already exist.

    Merged rather than duplicated: ``ApplicationEvent`` is the durable lifecycle timeline
    (discovery, approval, policy decisions, status changes) and ``RunTrajectory.steps`` is the
    browser agent's own step log. Both are real; inventing a third logger to sit alongside
    them would guarantee the three disagreed.
    """
    entries: list[EvidenceLogEntry] = []

    events = (
        await db.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == app.id)
            .order_by(ApplicationEvent.occurred_at)
        )
    ).scalars().all()
    for event in events:
        entries.append(
            EvidenceLogEntry(
                at=_aware(event.occurred_at) or datetime.now(UTC),
                source="application",
                kind=str(event.event_type),
                message=event.summary,
                detail=event.detail,
                actor=event.actor,
            )
        )

    runs = (
        await db.execute(
            select(RunTrajectory)
            .where(RunTrajectory.application_id == app.id)
            .order_by(RunTrajectory.created_at)
        )
    ).scalars().all()
    for run in runs:
        started = _aware(run.created_at) or datetime.now(UTC)
        for index, step in enumerate(run.steps or []):
            entries.append(
                EvidenceLogEntry(
                    at=started,
                    source="automation",
                    kind=f"step_{index + 1}",
                    message=_step_text(step),
                    actor="agent",
                )
            )

    entries.sort(key=lambda e: e.at)
    return entries


def _step_text(step: Any) -> str:
    """One readable line from a trajectory step, whatever shape it was recorded in."""
    if isinstance(step, str):
        return step[:300]
    if isinstance(step, dict):
        for key in ("summary", "action", "goal", "message", "evaluation", "next_goal"):
            value = step.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
        return str(step)[:300]
    return str(step)[:300]


async def _failure_section(db: AsyncSession, app: Application) -> EvidenceFailure | None:
    """Why a failed application failed, in enough detail to act on.

    ``notes`` carries the message the worker recorded; the harness diagnosis, when the review
    job has run, adds a failure class and root cause. Retry is offered only where the
    lifecycle genuinely supports it — a terminal FAILED row can be re-queued, and that is a
    real endpoint, not a button that does nothing.
    """
    if app.status != ApplicationStatus.FAILED:
        return None

    run = (
        await db.execute(
            select(RunTrajectory)
            .where(RunTrajectory.application_id == app.id)
            .order_by(RunTrajectory.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    failure_class: str | None = None
    root_cause: str | None = None
    if run is not None:
        diagnosis = (
            await db.execute(select(RunDiagnosis).where(RunDiagnosis.run_id == run.id))
        ).scalar_one_or_none()
        if diagnosis is not None:
            failure_class = str(diagnosis.failure_class)
            root_cause = diagnosis.root_cause or None
        verdict = (
            await db.execute(select(RunVerdict).where(RunVerdict.run_id == run.id))
        ).scalar_one_or_none()
        if verdict is not None and not root_cause:
            root_cause = verdict.reason or None

    return EvidenceFailure(
        message=app.notes or "The run failed without recording a reason.",
        failure_class=failure_class,
        root_cause=root_cause,
        failed_at=_aware(app.updated_at),
        url=app.application_url,
        step_count=len(run.steps or []) if run is not None else None,
        can_retry=True,
    )


async def build_evidence(db: AsyncSession, app: Application) -> ApplicationEvidence:
    """Assemble the full evidence bundle for one application."""
    job = await db.get(Job, app.job_id)
    resume = await db.get(Resume, app.resume_id) if app.resume_id else None
    platform = app.portal or (job.platform if job else None)

    logs = await _log_entries(db, app)
    evidence = ApplicationEvidence(
        application_id=app.id,
        job=_job_section(job, app),
        submission=_submission_section(app),
        resume=_resume_section(resume),
        cover_letter=_cover_letter_section(app),
        account=await _account_section(db, app, platform),
        failure=await _failure_section(db, app),
        log=logs,
        log_recorded=bool(logs),
    )
    logger.info(
        "evidence.built",
        application_id=app.id,
        log_entries=len(logs),
        has_job=evidence.job.recorded,
    )
    return evidence
