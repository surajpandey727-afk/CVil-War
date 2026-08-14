"""Run and store a job-vs-CV fit analysis.

The layer between the pure analyser (:mod:`app.core.fit`) and everything with side effects:
loading the job and CV, calling the model, persisting the result so reopening a job does not
pay for it again, and — the part that matters most for trust — noticing when a stored analysis
was made against a *different* CV than the one now selected.

Storage reuses ``ApplicationEvent``-style JSON rather than a new table: an analysis is a
snapshot, not an entity with a lifecycle, and it is keyed on ``(job_id, resume_id)`` because
that pair is exactly what determines the answer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ats.experience_analyzer import SENIORITY_TERMS
from app.core.fit.analyzer import (
    build_index,
    build_recommendations,
    overall_score,
    score_categories,
    verify_matches,
)
from app.core.fit.requirements import (
    SYSTEM_PROMPT,
    _LlmResult,
    keyword_requirements,
    render_prompt,
    to_matches,
)
from app.core.job_discovery.location import location_matches
from app.models.fit_analysis import FitAnalysisRecord
from app.models.job import Job
from app.models.resume import Resume
from app.schemas.fit import FitAnalysis, RequirementMatch

logger = structlog.get_logger(__name__)


def detect_seniority(text: str) -> str:
    """The seniority a piece of text reads as, or empty.

    Reuses the vocabulary the experience analyser already carries so the job page and the ATS
    scorer cannot disagree about what "senior" means.
    """
    lowered = (text or "").casefold()
    for level, terms in SENIORITY_TERMS.items():
        if any(term in lowered for term in terms):
            return str(level)
    return ""


async def _extract(
    db: AsyncSession, user_id: str, job: Job, cv_text: str
) -> tuple[list[RequirementMatch], str, str]:
    """Requirements and evidence, preferring the model and falling back to keywords.

    Returns ``(matches, method, model)``. Any LLM failure — no key, gateway down, malformed
    output — degrades to the keyword route rather than failing the request, because a weaker
    analysis the operator can see is worth more than an error page.
    """
    from app.core.llm.factory import build_llm_client_for_user

    try:
        client = await build_llm_client_for_user(db, user_id)
        result = await client.complete_with_structured_output(
            prompt=render_prompt(
                title=job.title or "",
                company=job.company or "",
                description=job.description or "",
                cv_text=cv_text,
            ),
            output_schema=_LlmResult,
            system_prompt=SYSTEM_PROMPT,
            purpose="job_analysis",
        )
        matches = to_matches(result)
        if matches:
            return matches, "llm", getattr(client, "model", "") or ""
        logger.warning("fit.llm_returned_nothing", job_id=job.id)
    except Exception as exc:
        logger.warning("fit.llm_unavailable", job_id=job.id, error=str(exc))

    tagged = job.skills_required or {}
    skills = tagged.get("required", []) if isinstance(tagged, dict) else []
    return (
        keyword_requirements(
            description=job.description or "", tagged_skills=list(skills), cv_text=cv_text
        ),
        "keyword",
        "",
    )


async def analyse(
    db: AsyncSession,
    *,
    user_id: str,
    job: Job,
    resume: Resume,
    target_location: str = "",
    salary_expectation_k: int = 0,
) -> FitAnalysis:
    """Assess one CV against one job, and persist the result."""
    cv_text = resume.content_text or ""
    index = build_index(cv_text)

    raw_matches, method, model = await _extract(db, user_id, job, cv_text)
    # Independent of how the matches were produced: nothing claims CV evidence unless that
    # text is actually in the CV.
    matches, rejected = verify_matches(index, raw_matches)
    if rejected:
        logger.info("fit.claims_rejected", job_id=job.id, rejected=rejected, method=method)

    job_facts: dict[str, object] = {
        "seniority": detect_seniority(f"{job.title} {job.description or ''}"),
        "cv_seniority": detect_seniority(cv_text),
        "industry": (job.skills_required or {}).get("industry")
        if isinstance(job.skills_required, dict) else None,
        "cv_industry": None,
    }
    if job.location:
        matched = location_matches(target_location, job.location, remote=bool(job.remote)) \
            if target_location else None
        if matched is not None:
            job_facts["location_fit"] = 1.0 if matched else 0.0
            job_facts["location_reason"] = (
                f"{job.location} matches your target of {target_location}."
                if matched
                else f"{job.location} is outside your target of {target_location}."
            )
    if job.salary_range:
        from app.services.policy import parse_salary_k

        top = parse_salary_k(job.salary_range)
        if top:
            job_facts["salary_max_k"] = top
            if salary_expectation_k:
                job_facts["salary_expectation_k"] = salary_expectation_k

    categories, not_assessed = score_categories(matches, job_facts=job_facts)
    analysis = FitAnalysis(
        job_id=job.id,
        resume_id=resume.id,
        resume_name=resume.name,
        overall=overall_score(categories),
        categories=categories,
        not_assessed=not_assessed,
        matches=matches,
        recommendations=build_recommendations(matches),
        method=method,
        model=model,
        analysed_at=datetime.now(UTC),
    )

    await _store(db, user_id, analysis)
    return analysis


async def _store(db: AsyncSession, user_id: str, analysis: FitAnalysis) -> None:
    """Persist the analysis for this (job, resume), replacing any earlier one.

    Replaced rather than appended: the question "how does this CV fit this job" has one
    current answer, and keeping a history of superseded scores would only invite the UI to
    show a stale one.
    """
    existing = (
        await db.execute(
            select(FitAnalysisRecord).where(
                FitAnalysisRecord.job_id == analysis.job_id,
                FitAnalysisRecord.resume_id == analysis.resume_id,
            )
        )
    ).scalar_one_or_none()
    payload = json.loads(analysis.model_dump_json())
    if existing is None:
        db.add(FitAnalysisRecord(
            user_id=user_id,
            job_id=analysis.job_id,
            resume_id=analysis.resume_id,
            overall=analysis.overall,
            method=analysis.method,
            payload=payload,
        ))
    else:
        existing.overall = analysis.overall
        existing.method = analysis.method
        existing.payload = payload
    await db.commit()


async def load_stored(
    db: AsyncSession, *, job_id: str, resume_id: str | None = None
) -> FitAnalysis | None:
    """The most recent stored analysis for a job, optionally pinned to one CV.

    When ``resume_id`` is given and the stored analysis was made against a different CV, the
    result comes back with ``stale_reason`` set rather than being hidden — the operator should
    see the previous assessment and be told it was for another CV, not be shown nothing.
    """
    query = select(FitAnalysisRecord).where(FitAnalysisRecord.job_id == job_id)
    if resume_id:
        query = query.where(FitAnalysisRecord.resume_id == resume_id)
    record = (
        await db.execute(query.order_by(FitAnalysisRecord.updated_at.desc()).limit(1))
    ).scalar_one_or_none()
    if record is None:
        return None

    analysis = FitAnalysis.model_validate(record.payload)
    analysis.cached = True
    if resume_id and record.resume_id != resume_id:
        analysis.stale_reason = (
            f"This assessment was made against “{analysis.resume_name}”, not the CV you have "
            "selected. Re-run it to compare the current one."
        )
    return analysis
