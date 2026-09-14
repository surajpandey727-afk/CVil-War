"""Which of the user's résumés best fits a given job, and a short synopsis of why.

Scores every non-archived résumé through the existing ATS scorer (``services.resume.
score_resume`` — the fast, non-LLM path already used by the per-job Fit tab), ranks them, and
explains the winner from the scorer's own missing-skills/suggestions output. Deliberately does
NOT invoke the richer LLM-backed fit analyser (``services.fit``) here: this backs a widget that
should respond the moment a job is opened, and running an LLM call once per résumé every time
would make it slow and, under ``ZERO_COST_MODE``, potentially unavailable. The richer analysis
stays one click away via "View full analysis" (the existing FitPanel).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resume import Resume
from app.schemas.resume import ResumeScoreRequest
from app.schemas.resume_recommendation import ResumeRanking, ResumeRecommendation
from app.services import resume as resume_service

#: How many of the runner-up's missing skills to name in the synopsis. Enough to be
#: actionable, short enough to read at a glance in a floating widget.
_MAX_SUGGESTED_SKILLS = 3
#: A score gap this small or smaller is "close enough to mention" in the synopsis — chosen so
#: a genuinely close call is flagged without turning every recommendation into a hedge.
_CLOSE_CALL_THRESHOLD = 0.03


async def recommend_best_resume(db: AsyncSession, job_id: str) -> ResumeRecommendation:
    """Score every one of the current user's résumés against ``job_id`` and rank them.

    No explicit ``user_id`` parameter: ``Resume`` is a ``TenantMixin`` entity, so the
    tenant-scoping filter already restricts the query to the requesting user — the same
    pattern ``services.resume.list_resumes`` already follows.

    Archived résumés are excluded — they were sent to a specific past employer and are not
    a live candidate for a new application (see ``services.resume.delete_resume``'s own
    reasoning for why archiving, not deletion, is what keeps them around at all).
    """
    resumes = (
        (
            await db.execute(
                select(Resume).where(Resume.archived_at.is_(None)).order_by(Resume.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not resumes:
        return ResumeRecommendation(
            job_id=job_id,
            recommended_resume_id=None,
            rankings=[],
            synopsis="No résumés uploaded yet — add one to see a match score for this job.",
        )

    rankings: list[ResumeRanking] = []
    for resume in resumes:
        score = await resume_service.score_resume(db, resume.id, ResumeScoreRequest(job_id=job_id))
        rankings.append(
            ResumeRanking(resume_id=resume.id, resume_name=resume.name, score=score)
        )

    rankings.sort(key=lambda item: item.score.overall_score, reverse=True)
    top = rankings[0]
    return ResumeRecommendation(
        job_id=job_id,
        recommended_resume_id=top.resume_id,
        rankings=rankings,
        synopsis=_build_synopsis(rankings),
    )


def _build_synopsis(rankings: list[ResumeRanking]) -> str:
    """One short paragraph: who wins, by how much, and what to change."""
    top = rankings[0]
    pct = round(top.score.overall_score * 100)
    sentences = [f'"{top.resume_name}" scores highest at {pct}% match.']

    if len(rankings) > 1:
        runner_up = rankings[1]
        gap = top.score.overall_score - runner_up.score.overall_score
        if gap <= _CLOSE_CALL_THRESHOLD:
            runner_pct = round(runner_up.score.overall_score * 100)
            sentences.append(
                f'It\'s a close call with "{runner_up.resume_name}" ({runner_pct}%).'
            )

    if top.score.missing_skills:
        skills = ", ".join(top.score.missing_skills[:_MAX_SUGGESTED_SKILLS])
        sentences.append(f"Consider adding: {skills}.")
    elif top.score.suggestions:
        sentences.append(top.score.suggestions[0])

    return " ".join(sentences)
