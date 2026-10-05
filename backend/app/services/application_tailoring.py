"""Tailor a résumé for one application and attach it, with the score of the file that results.

The bulk "Needs action" flow calls this once per selected application. It is deliberately the
same path as the job drawer's "Get Tailored Resume": the same in-place PDF editing, the same
claim validation, the same ATS evaluation of the generated file. All it adds is the choice of
base résumé (the best match for this job when none is given) and attaching the result to the
application, so approving it submits exactly the file whose score was shown.

Calling it twice for the same application and résumé reuses the existing version rather than
spending another LLM call or creating a duplicate; ``regenerate`` forces a new one.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GenerationError, RecordNotFoundError
from app.models.enums import ApplicationEventType, ApplicationStatus, ResumeType
from app.models.job import Job
from app.models.resume import Resume
from app.schemas.ats import ApplicationTailorRequest, ApplicationTailorResponse
from app.schemas.resume import ResumeGenerateRequest
from app.services import application as app_service
from app.services import ats_evaluation as ats
from app.services import resume as resume_service
from app.services.timeline import record_event

logger = structlog.get_logger(__name__)

#: Applications whose résumé can still be changed.
_EDITABLE = {ApplicationStatus.PENDING_REVIEW, ApplicationStatus.QUEUED}


async def _choose_base(
    db: AsyncSession, user_id: str, app, job: Job, requested: str | None
) -> Resume:
    if requested:
        base = await resume_service.get_resume(db, requested)
    elif app.resume_id:
        current = await resume_service.get_resume(db, app.resume_id)
        # A tailored version is always re-derived from its own base, never from itself.
        base = (
            await resume_service.get_resume(db, current.base_resume_id)
            if current.type != ResumeType.BASE and current.base_resume_id
            else current
        )
    else:
        loader = ats.ResumeLoader(user_id)
        try:
            best = await ats.best_for_job(loader, await ats.candidate_resumes(db), job)
        finally:
            loader.close()
        if best is None:
            raise GenerationError("Upload a résumé first: there is nothing to tailor.")
        base = best[0].resume
    if base.type != ResumeType.BASE:
        raise GenerationError(
            "Tailoring starts from one of your uploaded résumés, not from a tailored copy."
        )
    return base


async def tailor_for_application(
    db: AsyncSession, user_id: str, app_id: str, request: ApplicationTailorRequest
) -> ApplicationTailorResponse:
    app = await app_service.get_application(db, app_id)
    if app.status not in _EDITABLE:
        raise ValueError(
            f"A résumé can only be changed before an application is approved (this one is "
            f"{app.status})."
        )
    job = await db.get(Job, app.job_id)
    if job is None:
        raise RecordNotFoundError("Job", app.job_id)
    if not ats.usable_posting(job):
        raise GenerationError(
            "This posting has no description, so there is nothing to tailor the résumé to."
        )

    base = await _choose_base(db, user_id, app, job, request.base_resume_id)
    tailored = await resume_service.generate_tailored_resume(
        db,
        ResumeGenerateRequest(base_resume_id=base.id, job_id=job.id, regenerate=request.regenerate),
        user_id,
    )

    audit = tailored.tailoring_audit or {}
    app.resume_id = tailored.id
    # The application's score is the score of the file it will submit, taken from that file.
    app.ats_score = tailored.ats_score
    await record_event(
        db,
        app,
        ApplicationEventType.CV_TAILORED,
        f"Résumé tailored for this role from “{base.name}”",
        detail=audit.get("generation_status"),
        payload={
            "resume_id": tailored.id,
            "base_resume_id": base.id,
            "ats_before": audit.get("original_ats_score"),
            "ats_after": audit.get("final_ats_score"),
        },
        actor="user",
    )
    await db.commit()
    await db.refresh(app)

    evaluation = (audit.get("evaluation_after") or None) if isinstance(audit, dict) else None
    summary = None
    if evaluation:
        from app.schemas.ats import MatchSummary, TierSummary

        summary = MatchSummary(
            ats_match=round(evaluation["ats_match"] / 100, 4),
            parsing=round(evaluation["parsing"] / 100, 4),
            shortlist=round(evaluation["shortlist"] / 100, 4),
            band=evaluation["band"],
            shortlist_band=evaluation["shortlist_band"],
            tiers={k: TierSummary(**v) for k, v in evaluation["tiers"].items()},
            top_gaps=[f["requirement"] for f in evaluation["missing"] if f["tier"] == "critical"][
                :5
            ],
            constrained_by=evaluation.get("constrained_by", [])[:5],
            recruiter_signal=evaluation["recruiter"]["signal"],
            tailoring_limit=evaluation["verdict"].get("tailoring_limit", ""),
        )
    return ApplicationTailorResponse(
        application=app_service.application_to_response(app),
        resume=tailored,
        ats_before=(audit.get("original_ats_score") or 0) / 100
        if audit.get("original_ats_score") is not None
        else None,
        ats_after=tailored.ats_score,
        status=str(audit.get("generation_status") or ""),
        target_note=str(audit.get("ats_target_note") or ""),
        summary=summary,
    )
