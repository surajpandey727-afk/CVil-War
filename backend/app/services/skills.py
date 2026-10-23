"""Skill Radar service: aggregate role demand, enrich from the live corpus, score a résumé.

The curated knowledge base (``core/skills``) is the floor. When the account already holds jobs,
this layer counts how many of them mention each skill and passes those counts through, so the
ranking reflects the candidate's *actual* market when there is one and the curation when there is
not - the distinction the owner kept hitting: a brand-new account, or a discovery worker that has
not run, still gets a useful Radar.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.skills.aggregate import SkillHit, aggregate, categories_in_order, match_resume
from app.core.skills.catalog import SKILLS
from app.models.job import Job
from app.schemas.skills import (
    AggregatedSkillOut,
    SkillAggregateResponse,
    SkillHitOut,
    SkillScoreResponse,
)
from app.services.resume import get_resume

logger = structlog.get_logger(__name__)

#: Cap the corpus scan so the endpoint stays fast on a large account. The most recent jobs are
#: the most relevant to "what is being asked for now" anyway.
_CORPUS_SCAN_LIMIT = 400


async def _corpus_counts(db: AsyncSession) -> dict[str, int]:
    """How many recent stored jobs mention each skill. Empty when the corpus is empty.

    Tenant scoping is automatic (the ORM SELECT is filtered to the current user), so this only
    ever reads the caller's own jobs.
    """
    rows = (
        await db.execute(
            select(Job.title, Job.description)
            .order_by(Job.created_at.desc())
            .limit(_CORPUS_SCAN_LIMIT)
        )
    ).all()
    if not rows:
        return {}

    from app.core.skills.aggregate import _present  # local: internal matcher, not public API

    counts: dict[str, int] = {}
    for title, description in rows:
        low = f"{title or ''}\n{description or ''}".lower()
        for key, skill in SKILLS.items():
            if _present(skill, low):
                counts[key] = counts.get(key, 0) + 1
    return counts


async def aggregate_skills(db: AsyncSession, titles: list[str]) -> SkillAggregateResponse:
    """Merge the selected roles into one ranked demand list, enriched by the live corpus."""
    counts = await _corpus_counts(db)
    agg = aggregate(titles, counts or None)
    return SkillAggregateResponse(
        titles=titles,
        categories=categories_in_order(),
        corpus_used=bool(counts),
        skills=[
            AggregatedSkillOut(
                key=a.skill.key,
                label=a.skill.label,
                category=a.skill.category,
                demand=a.demand,
                roles_wanting=a.roles_wanting,
                must_have=a.must_have,
                ats=a.skill.ats,
                corpus_count=a.corpus_count,
            )
            for a in agg
        ],
    )


async def score_resume_against_roles(
    db: AsyncSession, resume_id: str, titles: list[str]
) -> SkillScoreResponse:
    """Score one résumé's text against the skills the selected roles want."""
    resume = await get_resume(db, resume_id)  # raises/404s via the route if missing
    counts = await _corpus_counts(db)
    report = match_resume(resume.content_text or "", titles, counts or None)

    def out(h: SkillHit) -> SkillHitOut:
        return SkillHitOut(
            key=h.skill.key,
            label=h.skill.label,
            category=h.skill.category,
            demand=h.demand,
            roles_wanting=h.roles_wanting,
            must_have=h.must_have,
            ats=h.skill.ats,
            present=h.present,
            matched_form=h.matched_form,
        )

    return SkillScoreResponse(
        resume_id=resume.id,
        resume_name=resume.name,
        titles=titles,
        score=report.score,
        must_have_score=report.must_have_score,
        band=report.band,
        matched_count=len(report.matched),
        total_count=len(report.hits),
        hits=[out(h) for h in report.hits],
        top_to_add=[out(h) for h in report.top_to_add],
    )
