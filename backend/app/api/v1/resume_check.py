"""Résumé checker routes: a fast deterministic check and a separate Claude review."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.core.ratelimit import rate_limit
from app.schemas.resume_check import (
    ResumeCheckRequest,
    ResumeCheckResponse,
    ResumeReviewResponse,
)
from app.services import resume_check as service

router = APIRouter()

# The review makes a paid LLM call; cap it per client like the other LLM routes.
_COSTLY = Depends(rate_limit(30, 60))


@router.post("/check", response_model=ResumeCheckResponse, summary="Check a résumé")
async def check_resume(
    data: ResumeCheckRequest,
    db: AsyncSession = Depends(get_tenant_db),
) -> ResumeCheckResponse:
    """Deterministic fit score, evidence, gaps ranked by UK demand, ATS coverage, section
    review and rule-based suggestions for one résumé against a job or the Radar role set."""
    return await service.check(db, data)


@router.post(
    "/review",
    response_model=ResumeReviewResponse,
    dependencies=[_COSTLY],
    summary="Claude's narrative review of a résumé",
)
async def review_resume(
    data: ResumeCheckRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> ResumeReviewResponse:
    """Narrative review and rewrites from Claude, each validated against the experience policy
    before it is returned. Reports unavailability instead of failing."""
    return await service.review(db, user.id, data)
