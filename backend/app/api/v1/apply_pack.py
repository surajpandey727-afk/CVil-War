"""GET /applications/{id}/pack — the ready-to-copy application pack (see core.apply_pack)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_db
from app.config.settings import get_settings
from app.core.apply_pack import build_answers, checklist
from app.models.job import Job
from app.models.resume import Resume
from app.models.user_settings import UserSettings
from app.schemas.resume_check import ResumeCheckRequest
from app.services import application as app_service

router = APIRouter()


class PackAnswer(BaseModel):
    question: str
    answer: str
    evidence_status: str
    note: str = ""


class PackDocument(BaseModel):
    name: str
    download_path: str


class ApplyPack(BaseModel):
    application_id: str
    job_title: str
    company: str
    employer_url: str | None
    location: str | None
    #: Why this needs doing by hand (or None when the agent can submit it).
    manual_reason: str | None
    cv: PackDocument | None
    has_cover_letter: bool
    fit_overall: float | None
    answers: list[PackAnswer]
    checklist: list[str]


@router.get("/{app_id}/pack", response_model=ApplyPack, summary="Ready-to-copy application pack")
async def get_pack(app_id: str, db: AsyncSession = Depends(get_tenant_db)) -> ApplyPack:
    app = await app_service.get_application(db, app_id)  # 404 + tenant ownership
    job = (await db.execute(select(Job).where(Job.id == app.job_id))).scalar_one_or_none()
    resume = (
        (await db.execute(select(Resume).where(Resume.id == app.resume_id))).scalar_one_or_none()
        if app.resume_id
        else None
    )
    settings_row = (await db.execute(select(UserSettings))).scalar_one_or_none()
    profile = (settings_row.candidate_profile if settings_row else None) or {}

    check = None
    if resume is not None and job is not None and len((resume.content_text or "").split()) >= 30:
        from app.services.resume_check import check as run_check

        check = await run_check(db, ResumeCheckRequest(resume_id=resume.id, job_id=job.id))

    cv = None
    if resume is not None:
        fmt = "pdf" if resume.file_path_pdf else "docx"
        cv = PackDocument(
            name=resume.name,
            download_path=f"/api/v1/resumes/{resume.id}/download?format={fmt}",
        )

    manual_reason = None
    if not get_settings().browser.live_apply:
        manual_reason = (
            "Automatic submission is off on this deployment, so this one is yours to send — "
            "everything you need is below."
        )

    title = (job.title if job else None) or "this role"
    company = (job.company if job else None) or ""
    answers = build_answers(
        profile=profile if isinstance(profile, dict) else {},
        resume_text=(resume.content_text if resume else "") or "",
        job_title=title,
        company=company,
        check=check,
    )
    return ApplyPack(
        application_id=app.id,
        job_title=title,
        company=company,
        employer_url=job.url if job else None,
        location=job.location if job else None,
        manual_reason=manual_reason,
        cv=cv,
        has_cover_letter=bool(app.cover_letter_path),
        fit_overall=check.score.overall if check else None,
        answers=[PackAnswer(**a.__dict__) for a in answers],
        checklist=checklist(
            has_cv=cv is not None,
            has_cover_letter=bool(app.cover_letter_path),
            url=job.url if job else None,
        ),
    )
