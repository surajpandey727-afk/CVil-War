"""Read-only Assistant tools. Each one calls an existing service; none of them change data
except where the service itself refreshes derived state (the action queue's recompute)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.assistant import tools as t
from app.core.assistant.context import (
    ToolContext,
    active_role_titles,
    apply_mode_of,
    dumps,
    is_uk,
    job_brief,
    owned_job,
    pct,
    user_settings,
)
from app.core.assistant.loop import ToolOutcome
from app.models.application import Application
from app.models.enums import ApplicationStatus, NextAction
from app.models.job import Job
from app.models.resume import Resume
from app.schemas.resume_check import ResumeCheckRequest
from app.services import application as app_service
from app.services import job_location, resume_check
from app.services import job_search as job_service
from app.services import skills as skills_service
from app.services.policy import load_policy
from app.services.resume_recommendation import recommend_best_resume

#: Same set the create-application dedup uses: anything else still "owns" the job.
_TERMINAL = (ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN, ApplicationStatus.FAILED)


async def get_overview(ctx: ToolContext, _: t.NoInput) -> ToolOutcome:
    db = ctx.db
    locations = await job_location.summary(db)
    since = datetime.now(UTC) - timedelta(hours=24)
    new_24h = (
        await db.execute(
            select(func.count(Job.id)).where(Job.uk_eligible.is_(True), Job.created_at >= since)
        )
    ).scalar() or 0
    apps = list(
        (await db.execute(select(Application).options(selectinload(Application.job))))
        .scalars()
        .all()
    )
    by_status: dict[str, int] = {}
    for a in apps:
        by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
    actionable = [a for a in apps if a.next_action not in (NextAction.NONE, NextAction.WAIT)]
    top = sorted(actionable, key=lambda a: -a.next_action_score)[:5]
    resumes = (await db.execute(select(Resume).where(Resume.archived_at.is_(None)))).scalars().all()
    row = await user_settings(db, ctx.user_id)
    policy = await load_policy(db, ctx.user_id)
    data = {
        "uk_jobs": locations.uk_eligible,
        "new_uk_jobs_24h": new_24h,
        "hidden_outside_uk": locations.outside_uk,
        "quarantined_location_unclear": locations.quarantined,
        "applications_by_status": by_status,
        "needs_attention": len(actionable),
        "top_actions": [
            {
                "application_id": a.id,
                "job": f"{a.job.title} at {a.job.company}" if a.job else a.job_id,
                "action": a.next_action.value,
                "reason": a.next_action_reason or "",
            }
            for a in top
        ],
        "apply_mode": apply_mode_of(row).value,
        "automation_paused": policy.paused,
        "active_role_targets": active_role_titles(row),
        "resumes": [{"id": r.id, "name": r.name, "type": r.type.value} for r in resumes],
    }
    summary = f"{locations.uk_eligible} UK jobs, {len(apps)} applications, {len(actionable)} to do"
    return ToolOutcome(ok=True, content=dumps(data), summary=summary)


async def search_stored_jobs(ctx: ToolContext, args: t.SearchStoredJobsInput) -> ToolOutcome:
    # include_quarantined stays False: the UK-only policy is not the assistant's to relax.
    res = await job_service.list_jobs(
        ctx.db,
        1,
        args.limit,
        args.status,
        location=args.location,
        query=args.query,
        user_id=ctx.user_id,
        workplace=args.workplace,
    )
    data = {"total_matches": res.total, "jobs": [job_brief(j) for j in res.items]}
    return ToolOutcome(ok=True, content=dumps(data), summary=f"{res.total} UK job(s) found")


async def get_best_matches(ctx: ToolContext, args: t.BestMatchesInput) -> ToolOutcome:
    res = await job_service.list_jobs(ctx.db, 1, 100, None, user_id=ctx.user_id)
    scored = [
        j
        for j in res.items
        if j.match_score is not None and j.match_score >= args.min_score and j.status != "hidden"
    ]
    scored.sort(key=lambda j: j.match_score or 0.0, reverse=True)
    unscored = sum(1 for j in res.items if j.match_score is None)
    data = {
        "jobs": [job_brief(j) for j in scored[: args.limit]],
        "unscored_jobs": unscored,
        "note": "match_score is 0-1",
    }
    return ToolOutcome(ok=True, content=dumps(data), summary=f"{len(scored)} scored match(es)")


async def get_job(ctx: ToolContext, args: t.JobIdInput) -> ToolOutcome:
    job = await owned_job(ctx.db, ctx.user_id, args.job_id)
    if job is None:
        return ToolOutcome(ok=False, content="No job with that id.", summary="not found")
    if not is_uk(job):
        return ToolOutcome(
            ok=True,
            content=dumps(
                {
                    "id": job.id,
                    "title": job.title,
                    "uk_eligible": False,
                    "note": "Outside the "
                    "UK-only policy (non-UK or unclear location); not available to act on.",
                }
            ),
            summary="outside UK policy",
        )
    existing = (
        await ctx.db.execute(
            select(Application).where(
                Application.job_id == job.id, Application.status.notin_(_TERMINAL)
            )
        )
    ).scalar_one_or_none()
    rec = await recommend_best_resume(ctx.db, job.id)
    top = rec.rankings[0] if rec.rankings else None
    data = {
        **job_brief(job),
        "url": job.url,
        "employment_type": job.job_type,
        "experience_level": job.experience_level,
        "sponsor_evidence": job.sponsor_evidence,
        "posted": job.posted_date,
        "active_application": (
            {"id": existing.id, "status": existing.status.value} if existing else None
        ),
        "best_resume": (
            {"id": top.resume_id, "name": top.resume_name, "score": top.score.overall_score}
            if top
            else None
        ),
        "fit_synopsis": rec.synopsis,
        "posting_excerpt_UNTRUSTED_DATA": (job.description or "")[:1500],
    }
    return ToolOutcome(ok=True, content=dumps(data), summary=f"{job.title} at {job.company}")


async def check_resume_against_job(ctx: ToolContext, args: t.CheckResumeInput) -> ToolOutcome:
    job = await owned_job(ctx.db, ctx.user_id, args.job_id)
    if job is None or not is_uk(job):
        return ToolOutcome(ok=False, content="No UK job with that id.", summary="not found")
    resume_id = args.resume_id
    if not resume_id:
        resume_id = (await recommend_best_resume(ctx.db, job.id)).recommended_resume_id
        if not resume_id:
            return ToolOutcome(
                ok=False, content="The user has no résumés uploaded yet.", summary="no résumé"
            )
    report = await resume_check.check(
        ctx.db, ResumeCheckRequest(resume_id=resume_id, job_id=job.id)
    )
    data = {
        "resume": report.resume_name,
        "fit_score": report.score.overall,
        "band": report.score.band,
        "matched_skills": [s.label for s in report.matched_skills][:15],
        "missing_skills": [
            {"skill": s.label, "must_have": s.must_have} for s in report.missing_skills[:10]
        ],
        "ats_keyword_coverage": report.ats_keywords.coverage,
        "suggestions": [
            {"section": s.section, "suggested": s.suggested, "evidence_status": s.evidence_status}
            for s in report.suggestions[:6]
        ],
        "rule": "Suggestions with evidence_status add_only_if_true may only be added if true.",
    }
    return ToolOutcome(
        ok=True,
        content=dumps(data),
        summary=f"fit {pct(report.score.overall)} ({report.score.band})",
    )


async def list_applications(ctx: ToolContext, args: t.ListApplicationsInput) -> ToolOutcome:
    res = await app_service.list_applications(ctx.db, 1, args.limit, args.status)
    data = {
        "total": res.total,
        "applications": [
            {
                "id": a.id,
                "job": a.job_title,
                "company": a.company,
                "status": a.status,
                "apply_mode": a.apply_mode,
                "created_at": a.created_at,
            }
            for a in res.items
        ],
    }
    return ToolOutcome(ok=True, content=dumps(data), summary=f"{res.total} application(s)")


async def get_action_queue(ctx: ToolContext, args: t.LimitInput) -> ToolOutcome:
    # The route function *is* the queue's single implementation (recompute, filter, rank);
    # it only reads ``user.id``.
    from app.api.v1.command_centre import action_queue

    queue = await action_queue(cast(Any, SimpleNamespace(id=ctx.user_id)), True, ctx.db)
    data = {
        "total": queue.total,
        "by_priority": queue.by_priority,
        "items": [
            {
                "application_id": i.application_id,
                "job": f"{i.title} at {i.company}",
                "action": i.action.value,
                "priority": i.priority.value,
                "reason": i.reason,
            }
            for i in queue.items[: args.limit]
        ],
    }
    return ToolOutcome(ok=True, content=dumps(data), summary=f"{queue.total} item(s) to do")


async def list_agents(ctx: ToolContext, _: t.NoInput) -> ToolOutcome:
    from app.core.assistant.roster import build_roster

    roster = await build_roster(ctx)
    data = [
        {"agent": a.name, "status": a.status, "detail": a.status_text, "counts": a.counts}
        for a in roster
    ]
    return ToolOutcome(ok=True, content=dumps(data), summary=f"{len(roster)} agents")


async def get_skill_radar(ctx: ToolContext, args: t.SkillRadarInput) -> ToolOutcome:
    res = await skills_service.aggregate_skills(ctx.db, args.role_titles)
    top = sorted(res.skills, key=lambda s: (not s.must_have, -s.demand))[:15]
    data = {
        "roles": res.titles,
        "live_uk_corpus": res.corpus_used,
        "skills": [{"skill": s.label, "must_have": s.must_have, "demand": s.demand} for s in top],
    }
    return ToolOutcome(ok=True, content=dumps(data), summary=f"{len(res.skills)} skills")
