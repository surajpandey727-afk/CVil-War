"""The AI Agents roster: one honest card per agent.

Status comes from real facts only — the latest ``AgentRun`` row the agent itself wrote, plus
configuration the agent depends on. Something that isn't configured on this deployment (no
queue worker, Gmail not connected, live apply off, no API key) is said in the status text
rather than shown as a healthy idle agent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from app.config.settings import get_settings
from app.core.assistant.context import ToolContext, active_role_titles, user_settings
from app.core.llm.client import anthropic_key_configured
from app.models.agent_run import AgentRun
from app.models.application import Application
from app.models.communication_event import CommunicationEvent
from app.models.enums import (
    AgentName,
    AgentRunStatus,
    ApplicationStatus,
    ResumeType,
    SponsorConfidence,
)
from app.models.job import Job
from app.models.resume import Resume
from app.schemas.assistant import AgentAction, AgentCard, AgentCount, AgentLastRun
from app.services import gmail_auth, job_location
from app.services.policy import load_policy

_STALE_RUNNING = timedelta(minutes=30)
_SPONSOR_SIGNAL = (
    SponsorConfidence.CONFIRMED_REGISTER,
    SponsorConfidence.KEYWORD_DETECTED,
    SponsorConfidence.LIKELY,
)


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _link(label: str, to: str) -> AgentAction:
    return AgentAction(label=label, kind="link", to=to)


async def _count(ctx: ToolContext, model: type, *where: ColumnElement[bool]) -> int:
    stmt = select(func.count(model.id))
    for clause in where:
        stmt = stmt.where(clause)
    return int((await ctx.db.execute(stmt)).scalar() or 0)


async def _latest_runs(ctx: ToolContext) -> dict[AgentName, AgentRun]:
    rows = (
        await ctx.db.execute(
            select(AgentRun)
            .where(AgentRun.user_id == ctx.user_id)
            .order_by(AgentRun.started_at.desc())
            .limit(200)
        )
    ).scalars()
    latest: dict[AgentName, AgentRun] = {}
    for row in rows:
        latest.setdefault(row.agent_name, row)
    return latest


def _from_run(run: AgentRun | None) -> tuple[str, AgentLastRun | None]:
    if run is None:
        return "idle", None
    last = AgentLastRun(
        status=run.status.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary=run.output_summary or run.input_summary,
        error=(run.error or "")[:300] or None,
    )
    if run.status == AgentRunStatus.RUNNING:
        fresh = datetime.now(UTC) - _aware(run.started_at) < _STALE_RUNNING
        return ("running" if fresh else "needs_attention"), last
    if run.status in (AgentRunStatus.ERROR, AgentRunStatus.NEEDS_REVIEW):
        return "needs_attention", last
    return "idle", last


def _run_text(status: str, last: AgentLastRun | None, idle_text: str) -> str:
    if last is None:
        return f"Hasn't run yet. {idle_text}".strip()
    if status == "running":
        return "Working now."
    if last.status == AgentRunStatus.ERROR.value:
        return "Last run failed — see its error below."
    if last.status == AgentRunStatus.NEEDS_REVIEW.value:
        return "Last run needs your review."
    if status == "needs_attention":
        return "Last run never finished (stuck)."
    return idle_text


async def build_roster(ctx: ToolContext) -> list[AgentCard]:
    settings = get_settings()
    runs = await _latest_runs(ctx)
    row = await user_settings(ctx.db, ctx.user_id)
    policy = await load_policy(ctx.db, ctx.user_id)
    titles = active_role_titles(row)
    queue_ok = ctx.pool is not None
    db_worker = settings.apply_dispatch == "db_queue"
    now = datetime.now(UTC)

    # Discovery
    d_status, d_last = _from_run(runs.get(AgentName.DISCOVERY))
    sched = (
        "Runs on the background schedule."
        if queue_ok
        else "No background scheduler on this deployment; it runs when you trigger it."
    )
    d_text = _run_text(d_status, d_last, sched)
    if not titles:
        d_status, d_text = "needs_attention", "No active role targets to search for. " + sched
    new_24h = await _count(
        ctx, Job, Job.uk_eligible.is_(True), Job.created_at >= now - timedelta(1)
    )
    discovery = AgentCard(
        key="discovery",
        name="Discovery",
        description="Finds new UK roles from your role targets across your enabled sources.",
        status=d_status,
        status_text=d_text,
        last_run=d_last,
        counts=[
            AgentCount(label="New UK jobs (24h)", value=new_24h),
            AgentCount(label="Active role targets", value=len(titles)),
        ],
        actions=(
            [AgentAction(label="Run discovery now", kind="confirm", action="run_discovery_now")]
            if titles
            else []
        )
        + [_link("Role targets", "/targets"), _link("Sources", "/sources")],
        section=_link("Jobs", "/jobs"),
    )

    # Eligibility
    e_status, e_last = _from_run(runs.get(AgentName.ELIGIBILITY))
    loc = await job_location.summary(ctx.db)
    sponsors = await _count(
        ctx,
        Job,
        Job.uk_eligible.is_(True),
        Job.sponsor_confidence.in_(_SPONSOR_SIGNAL),
    )
    eligibility = AgentCard(
        key="eligibility",
        name="Eligibility",
        description="Checks every role is in the UK and grades visa-sponsorship evidence.",
        status=e_status,
        status_text=_run_text(e_status, e_last, "Classifies jobs as they arrive."),
        last_run=e_last,
        counts=[
            AgentCount(label="UK-eligible jobs", value=loc.uk_eligible),
            AgentCount(label="Sponsor signal", value=sponsors),
            AgentCount(label="Location unclear", value=loc.quarantined),
        ],
        section=_link("Jobs", "/jobs"),
    )

    # Scoring
    s_status, s_last = _from_run(runs.get(AgentName.SCORING))
    scored = await _count(ctx, Job, Job.uk_eligible.is_(True), Job.match_score.is_not(None))
    scoring = AgentCard(
        key="scoring",
        name="Scoring",
        description="Matches each job against your best résumé and stores a 0-100 fit.",
        status=s_status,
        status_text=_run_text(s_status, s_last, "Scores jobs when they're opened or enriched."),
        last_run=s_last,
        counts=[
            AgentCount(label="Scored UK jobs", value=scored),
            AgentCount(label="Unscored", value=max(0, loc.uk_eligible - scored)),
        ],
        section=_link("Jobs", "/jobs"),
    )

    # Résumé (tailor + checker) — no run log of its own yet.
    active = await _count(ctx, Resume, Resume.archived_at.is_(None))
    tailored = await _count(ctx, Resume, Resume.type == ResumeType.TAILORED)
    resume = AgentCard(
        key="resume",
        name="Résumé",
        description="Tailors your CV per job and checks it, adding only what's true.",
        status="needs_attention" if active == 0 else "idle",
        status_text="Upload a résumé to start." if active == 0 else "Ready when you are.",
        tracks_runs=False,
        counts=[
            AgentCount(label="Active résumés", value=active),
            AgentCount(label="Tailored versions", value=tailored),
        ],
        actions=[_link("Résumés", "/resumes")],
        section=_link("Résumé checker", "/resume-checker"),
    )

    # Application
    a_status, a_last = _from_run(runs.get(AgentName.APPLICATION))
    staged = await _count(ctx, Application, Application.status == ApplicationStatus.PENDING_REVIEW)
    queued = await _count(
        ctx,
        Application,
        Application.status.in_((ApplicationStatus.APPROVED, ApplicationStatus.QUEUED)),
    )
    applied = await _count(ctx, Application, Application.status == ApplicationStatus.APPLIED)
    notes = []
    if not settings.browser.live_apply:
        notes.append("Live apply is off, so runs end in a simulated submit.")
    if not queue_ok and db_worker:
        notes.append("Approved applications wait for the DB-queue worker on the apply machine.")
    elif not queue_ok:
        notes.append("No queue worker here; approved applications run inline.")
    a_text = " ".join([_run_text(a_status, a_last, "Waiting for approved applications."), *notes])
    if policy.paused:
        a_status, a_text = "off", "Automation is paused in your policy; nothing is submitted."
    application = AgentCard(
        key="application",
        name="Application",
        description="Runs the apply pipeline for approved applications, gated by your policy.",
        status=a_status,
        status_text=a_text,
        last_run=a_last,
        counts=[
            AgentCount(label="Awaiting your review", value=staged),
            AgentCount(label="Approved / queued", value=queued),
            AgentCount(label="Applied", value=applied),
        ],
        actions=[_link("Automation policy", "/automation")],
        section=_link("Applications", "/applications"),
    )

    # Tracking
    t_status, t_last = _from_run(runs.get(AgentName.TRACKING))
    t_text = _run_text(t_status, t_last, "Watches Gmail for recruiter replies.")
    if not gmail_auth.is_configured():
        t_status, t_text = "off", "Gmail isn't set up on this deployment (no Google OAuth client)."
    elif not await gmail_auth.is_connected(ctx.db, ctx.user_id):
        t_status, t_text = (
            "needs_attention",
            "Gmail isn't connected yet. Connect it in Communications.",
        )
    events = await _count(
        ctx, CommunicationEvent, CommunicationEvent.occurred_at >= now - timedelta(days=7)
    )
    tracking = AgentCard(
        key="tracking",
        name="Tracking",
        description="Matches recruiter emails to your applications and updates their status.",
        status=t_status,
        status_text=t_text,
        last_run=t_last,
        counts=[AgentCount(label="Messages (7 days)", value=events)],
        section=_link("Communications", "/communications"),
    )

    # Assistant
    key_ok = anthropic_key_configured()
    assistant = AgentCard(
        key="assistant",
        name="Assistant",
        description="Your chief of staff: answers, plans, and runs the other agents on request.",
        status="idle" if key_ok else "off",
        status_text=(
            "Ready. Asks before anything consequential."
            if key_ok
            else "Off: ANTHROPIC_API_KEY isn't set on this deployment."
        ),
        tracks_runs=False,
        section=_link("Assistant", "/assistant"),
    )
    return [discovery, eligibility, scoring, resume, application, tracking, assistant]
