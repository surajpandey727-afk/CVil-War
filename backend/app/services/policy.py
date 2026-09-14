"""Load the operator's policy, assemble the facts, decide, and record the decision.

This is the layer between the pure engine (:mod:`app.core.policy`) and the database. It has
one job the engine deliberately cannot do: establish what is actually true right now — how
many applications went out today, whether this employer was applied to last week, whether
this posting is a duplicate — and hand those facts over as a :class:`PolicyContext`.

:func:`gate` is the single chokepoint. Every submission path goes through it, so a rule added
to the catalogue takes effect everywhere at once rather than in whichever caller remembered.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.policy import AutomationPolicy, PolicyContext, PolicyDecision, Verdict, evaluate
from app.models.application import Application
from app.models.enums import ApplicationEventType, ApplicationStatus
from app.models.job import Job
from app.models.user_settings import UserSettings

logger = structlog.get_logger(__name__)

#: Statuses that count as "a submission was made". FAILED is excluded on purpose: a failed
#: attempt did not reach the employer, so counting it against the daily cap would punish the
#: operator for the system's own outage.
_SUBMITTED = (
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.REJECTED,
    ApplicationStatus.OFFER,
)

#: Words dropped when deciding whether two titles describe the same role, for the §3.2
#: cooldown. Without this, "Senior Product Manager" and "Product Manager" look unrelated.
_TITLE_NOISE = frozenset(
    {"senior", "junior", "staff", "principal", "lead", "head", "chief", "of", "the", "and",
     "a", "an", "for", "to", "in", "at", "ii", "iii", "i", "sr", "jr", "uk", "london",
     "remote", "hybrid", "contract", "permanent", "fte"}
)

_SALARY_NUM = re.compile(r"(\d[\d,.]*)\s*(k)?", re.IGNORECASE)


def _naive(when: datetime) -> datetime:
    """Drop the tzinfo for comparison against the naive-UTC columns.

    The DateTime columns are timezone-naive and hold UTC, which is the convention the rest
    of the codebase already follows (see ``core.actions.engine``). Comparing an aware value
    against them raises on some drivers and silently misfilters on others.
    """
    return when.astimezone(UTC).replace(tzinfo=None)


def _aware(when: datetime | None) -> datetime | None:
    if when is None:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def title_key(title: str) -> frozenset[str]:
    """The meaningful words of a job title, for similarity comparison.

    Deliberately crude. The §3.2 cooldown only has to answer "is this the same role I already
    applied for", and an operator can always override; an embedding model here would cost
    money the zero-cost constraint does not allow and would be harder to explain when it got
    it wrong.
    """
    words = {w for w in re.split(r"\W+", (title or "").casefold()) if w}
    return frozenset(words - _TITLE_NOISE)


def titles_are_similar(a: str, b: str, *, threshold: float = 0.6) -> bool:
    """True when two titles plausibly describe the same role."""
    ka, kb = title_key(a), title_key(b)
    if not ka or not kb:
        return False
    return len(ka & kb) / min(len(ka), len(kb)) >= threshold


def parse_salary_k(raw: str | None) -> int | None:
    """Best-effort top-of-band in thousands from a free-text salary string.

    Returns ``None`` when nothing usable is present — which the rules treat as "no published
    band", not as zero. Getting that distinction wrong would silently discard most UK
    postings, since the majority do not publish a range.
    """
    if not raw:
        return None
    best: int | None = None
    for match in _SALARY_NUM.finditer(raw):
        digits = match.group(1).replace(",", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        if match.group(2):  # "75k"
            value *= 1000
        if value < 1000:  # an hourly or daily rate, or a stray number — not a band
            continue
        thousands = int(value / 1000)
        best = thousands if best is None else max(best, thousands)
    return best


async def load_policy(db: AsyncSession, user_id: str) -> AutomationPolicy:
    """The user's stored policy, or the shipped defaults if they have never saved one.

    A blob written before a clause existed validates fine and picks up that clause's default,
    so the policy strengthens itself as the catalogue grows rather than needing a migration.
    """
    row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        return AutomationPolicy()
    policy = AutomationPolicy.model_validate(row.automation or {})
    if not row.automation:
        # No blob yet: honour the one threshold that has always had its own column, so a user
        # who set it on the old settings screen does not silently get it reset to the default.
        policy.min_ats_score = row.min_ats_score
    return policy


async def build_context(
    db: AsyncSession,
    app: Application,
    job: Job | None,
    *,
    now: datetime | None = None,
    ats_score: float | None = None,
    eligibility_questions: list[str] | None = None,
    challenge_detected: bool = False,
) -> PolicyContext:
    """Gather every fact the rules may consult about this candidate submission.

    ``ats_score`` is passed in rather than read off the row because the worker scores just
    before the gate; ``None`` means *not scored*, which the match rule escalates on.
    """
    now = now or datetime.now(UTC)
    cutoff_day = _naive(now - timedelta(days=1))
    cutoff_hour = _naive(now - timedelta(hours=1))
    cutoff_week = _naive(now - timedelta(days=7))

    company = job.company if job else ""
    source_key = app.portal or (job.platform if job else "")

    submitted_today = await _count_since(db, cutoff_day)
    submitted_hour = await _count_since(db, cutoff_hour)

    company_week = 0
    if company:
        company_week = await _count_since(db, cutoff_week, company=company)

    last_at = await _last_submission_at(db, exclude_application_id=app.id)
    gap = int((now - last_at).total_seconds()) if last_at else None

    duplicate_id = await _duplicate_application_id(db, app)
    last_similar = (
        await _last_similar_application_at(db, app, company, job.title if job else "")
        if company
        else None
    )

    source_failures, first_run = await _source_history(db, source_key)

    return PolicyContext(
        now=now,
        job_title=job.title if job else "",
        company=company,
        source_key=source_key,
        salary_max_k=parse_salary_k(job.salary_range if job else None),
        seniority=(job.experience_level or "") if job else "",
        ats_score=ats_score,
        sponsor_confidence=str(job.sponsor_confidence or "") if job else "",
        submitted_today=submitted_today,
        submitted_this_hour=submitted_hour,
        submitted_to_company_this_week=company_week,
        seconds_since_last_submission=gap,
        duplicate_of_application_id=duplicate_id,
        last_similar_application_at=last_similar,
        consecutive_source_failures=source_failures,
        first_run_on_source=first_run,
        eligibility_questions=eligibility_questions or [],
        challenge_detected=challenge_detected,
    )


async def _count_since(
    db: AsyncSession, cutoff: datetime, *, company: str | None = None
) -> int:
    """Submissions since ``cutoff``. Tenant-scoped by the ORM filter, so no user_id here."""
    stmt = (
        select(func.count())
        .select_from(Application)
        .where(Application.status.in_(_SUBMITTED), Application.applied_at >= cutoff)
    )
    if company:
        stmt = stmt.join(Job, Job.id == Application.job_id).where(
            func.lower(Job.company) == company.casefold()
        )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _last_submission_at(
    db: AsyncSession, *, exclude_application_id: str
) -> datetime | None:
    stmt = (
        select(func.max(Application.applied_at))
        .where(
            Application.status.in_(_SUBMITTED),
            Application.applied_at.isnot(None),
            Application.id != exclude_application_id,
        )
    )
    return _aware((await db.execute(stmt)).scalar_one_or_none())


async def _duplicate_application_id(db: AsyncSession, app: Application) -> str | None:
    """An earlier application to this same posting, if one exists.

    Matched on ``job_id``, and — because the same posting is routinely discovered through two
    sources as two Job rows — also on the canonical id the dedup pass assigns.
    """
    job_ids = [app.job_id]
    job = await db.get(Job, app.job_id)
    if job is not None and job.canonical_job_id:
        siblings = (
            await db.execute(
                select(Job.id).where(Job.canonical_job_id == job.canonical_job_id)
            )
        ).scalars().all()
        job_ids = list({*job_ids, *siblings})

    stmt = (
        select(Application.id)
        .where(
            Application.job_id.in_(job_ids),
            Application.id != app.id,
            Application.status.in_(_SUBMITTED),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _last_similar_application_at(
    db: AsyncSession, app: Application, company: str, title: str
) -> datetime | None:
    """When a materially similar role at this employer was last applied to.

    Titles are compared in Python rather than SQL: the comparison is a word-overlap test, and
    pushing it into the database would mean either a LIKE that is wrong or an extension that
    is not available on SQLite.
    """
    if not title:
        return None
    stmt = (
        select(Application.applied_at, Job.title)
        .join(Job, Job.id == Application.job_id)
        .where(
            func.lower(Job.company) == company.casefold(),
            Application.id != app.id,
            Application.status.in_(_SUBMITTED),
            Application.applied_at.isnot(None),
        )
        .order_by(Application.applied_at.desc())
        .limit(50)
    )
    for applied_at, other_title in (await db.execute(stmt)).all():
        if titles_are_similar(title, other_title):
            return _aware(applied_at)
    return None


async def _source_history(db: AsyncSession, source_key: str) -> tuple[int, bool]:
    """``(consecutive recent failures, never succeeded here before)`` for one portal.

    "Consecutive" is measured over the most recent attempts on that portal, newest first, so
    a success resets the count the moment it happens.
    """
    if not source_key:
        return 0, False
    stmt = (
        select(Application.status)
        .join(Job, Job.id == Application.job_id)
        .where((Application.portal == source_key) | (Job.platform == source_key))
        .order_by(Application.updated_at.desc())
        .limit(25)
    )
    statuses = list((await db.execute(stmt)).scalars().all())
    failures = 0
    for status in statuses:
        if status is ApplicationStatus.FAILED:
            failures += 1
        elif status in _SUBMITTED:
            break
    first_run = not any(s in _SUBMITTED for s in statuses)
    return failures, first_run


async def gate(
    db: AsyncSession,
    app: Application,
    *,
    ats_score: float | None = None,
    now: datetime | None = None,
    eligibility_questions: list[str] | None = None,
    challenge_detected: bool = False,
    record: bool = True,
) -> PolicyDecision:
    """Decide whether this application may be submitted, and write the decision down.

    Recording is the point of doing this here rather than inline in the worker: policy §9
    requires that the operator can always answer "why did it apply to that?" and "why hasn't
    it applied to this?" without reading logs. The timeline entry carries the rule ids.
    """
    policy = await load_policy(db, app.user_id)
    job = await db.get(Job, app.job_id)
    ctx = await build_context(
        db,
        app,
        job,
        now=now,
        ats_score=ats_score,
        eligibility_questions=eligibility_questions,
        challenge_detected=challenge_detected,
    )
    decision = evaluate(policy, ctx)

    if record:
        await _record_decision(db, app, decision)

    logger.info(
        "policy.decided",
        application_id=app.id,
        verdict=decision.verdict.value,
        rules=[o.rule_id for o in decision.outcomes],
    )
    return decision


async def _record_decision(
    db: AsyncSession, app: Application, decision: PolicyDecision
) -> None:
    """Append the decision to the timeline. Refuses are the ones worth reading later.

    An ALLOW with nothing to say is not recorded — a timeline with one "policy allowed this"
    entry per application is noise that buries the entries that matter.
    """
    from app.services.timeline import record_event

    if decision.verdict is Verdict.ALLOW and not decision.outcomes:
        return

    event_type = (
        ApplicationEventType.USER_ACTION_REQUIRED
        if decision.verdict is Verdict.ESCALATE
        else ApplicationEventType.APPLICATION_PAUSED
        if decision.verdict is Verdict.HOLD
        else ApplicationEventType.ERROR
        if decision.verdict is Verdict.BLOCK
        else ApplicationEventType.NOTE_ADDED
    )
    await record_event(
        db,
        app,
        event_type,
        decision.summary,
        actor="policy",
        payload={
            "verdict": decision.verdict.value,
            "policy_version": decision.policy_version,
            "outcomes": [o.model_dump(mode="json") for o in decision.outcomes],
        },
    )
