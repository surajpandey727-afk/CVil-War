"""Résumé checker service: load the résumé and target, run the deterministic check, and layer
Claude's validated narrative review on top (see ``core.resume_check``)."""

from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ParseError, RecordNotFoundError
from app.core.resume_check.check import CheckInput, build_check
from app.core.resume_check.review import SYSTEM_PROMPT, LlmReview, build_prompt, validate_review
from app.core.resume_check.targets import job_target, roles_target
from app.models.enums import LLMPurpose
from app.models.job import Job
from app.schemas.resume_check import (
    CheckTarget,
    ResumeCheckRequest,
    ResumeCheckResponse,
    ResumeReviewResponse,
)
from app.services.resume import get_resume
from app.services.skills import _CORPUS_SCAN_LIMIT, _corpus_counts

logger = structlog.get_logger(__name__)


async def _uk_jobs_scanned(db: AsyncSession) -> int:
    """How many UK-eligible jobs the demand counts were taken from (capped like the scan)."""
    total = await db.scalar(select(func.count()).select_from(Job).where(Job.uk_eligible.is_(True)))
    return min(int(total or 0), _CORPUS_SCAN_LIMIT)


async def _inputs(db: AsyncSession, req: ResumeCheckRequest) -> CheckInput:
    resume = await get_resume(db, req.resume_id)
    text = resume.content_text or ""
    if len(text.split()) < 30:
        raise ParseError(
            resume.name,
            "No readable text was extracted from this résumé, so it cannot be checked. "
            "Re-upload it as a text-based PDF or DOCX.",
        )
    if req.job_id:
        job = (await db.execute(select(Job).where(Job.id == req.job_id))).scalar_one_or_none()
        if job is None:
            raise RecordNotFoundError("Job", req.job_id)
        target = job_target(job.title or "", job.description or "")
        info = CheckTarget(kind="job", job_id=job.id, title=job.title or "", company=job.company)
    else:
        target = roles_target(req.role_titles)
        info = CheckTarget(
            kind="roles", title=", ".join(req.role_titles), role_titles=req.role_titles
        )
    counts = await _corpus_counts(db)
    scanned = await _uk_jobs_scanned(db) if counts else 0
    return CheckInput(
        resume_id=resume.id,
        resume_name=resume.name,
        resume_text=text,
        target=target,
        target_info=info,
        uk_demand=counts,
        uk_jobs_scanned=scanned,
    )


async def check(db: AsyncSession, req: ResumeCheckRequest) -> ResumeCheckResponse:
    response, _ = build_check(await _inputs(db, req))
    return response


async def review(db: AsyncSession, user_id: str, req: ResumeCheckRequest) -> ResumeReviewResponse:
    """Claude's narrative review. Any failure is reported, never raised — the deterministic
    check is the product; the review is an addition to it."""
    from app.core.llm.factory import build_llm_client_for_user

    inp = await _inputs(db, req)
    check_response, _ = build_check(inp)
    try:
        client = await build_llm_client_for_user(db, user_id)
        parsed, meta = await client.complete_json(
            build_prompt(check_response, inp.resume_text),
            LlmReview,
            system_prompt=SYSTEM_PROMPT,
            purpose=LLMPurpose.ATS_REVIEW.value,
        )
    except Exception as exc:
        logger.warning("resume_review_unavailable", error_type=type(exc).__name__)
        return ResumeReviewResponse(available=False, detail=_unavailable_reason(exc))

    assert isinstance(parsed, LlmReview)
    notes, suggestions, rejected = validate_review(parsed, inp.resume_text)
    if rejected:
        logger.info("resume_review_items_rejected", count=rejected)
    return ResumeReviewResponse(
        available=True,
        model=meta.model,
        summary=parsed.summary.strip(),
        section_notes=notes,
        suggestions=suggestions,
        rejected_count=rejected,
    )


def _unavailable_reason(exc: Exception) -> str:
    text = str(exc)
    # Cause only — the UI adds that the deterministic check above still stands.
    if "ANTHROPIC_API_KEY is not set" in text:
        return "The server has no Anthropic API key configured."
    if "Failed to parse structured output" in text:
        return "The AI reply didn't match the expected format, so it was discarded."
    return "The AI reviewer couldn't be reached just now. Try again shortly."
