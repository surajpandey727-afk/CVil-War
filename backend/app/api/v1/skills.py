"""Skill Radar API: aggregate in-demand skills for a set of roles, and score a résumé against them.

Tenant-scoped (both routes read the caller's own corpus/résumés through ``get_tenant_db``). The
aggregate route also answers for roles the account has no jobs for yet — the curated knowledge
base stands in for an empty corpus, which is the whole point.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.core.skills.roles import known_titles
from app.schemas.skills import (
    SkillAggregateRequest,
    SkillAggregateResponse,
    SkillScoreRequest,
    SkillScoreResponse,
)
from app.services import skills as skills_service

router = APIRouter()


@router.get("/roles", summary="Role titles with a curated skill profile")
async def list_roles(user: CurrentUser) -> list[str]:
    """The roles the Radar has an explicit profile for — the suggested selections. Any other
    title still works via its family default, but these are the ones worth offering first."""
    return known_titles()


@router.post(
    "/aggregate",
    response_model=SkillAggregateResponse,
    summary="Aggregate the in-demand skills across selected roles",
)
async def aggregate_skills(
    data: SkillAggregateRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> SkillAggregateResponse:
    return await skills_service.aggregate_skills(db, data.titles)


@router.post(
    "/score",
    response_model=SkillScoreResponse,
    summary="Score a résumé against the skills the selected roles want",
)
async def score_resume(
    data: SkillScoreRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> SkillScoreResponse:
    return await skills_service.score_resume_against_roles(db, data.resume_id, data.titles)
