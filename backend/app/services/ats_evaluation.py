"""Score stored résumés against stored jobs and applications with the ATS evaluation engine.

One place decides how a résumé is read, how a posting is turned into text and where the result is
kept, so the Jobs list, the Applications list, the job drawer and the tailoring flow all show
the same number for the same pair.

Why this exists: scores used to be computed one request at a time, only when a drawer was
opened, behind a rate limit, or at the moment of applying. A list of thirty rows therefore showed
a score on a handful and nothing on the rest, and ``jobs.match_score`` was never written at all.
Bulk scoring here is one request, fast (no model, no spaCy) and written back.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ats_engine import Evaluation, ParsingReport, analyse, evaluate, parsing_report
from app.core.resume_tailoring.extract import extract_from_docx, parse_resume_text
from app.core.resume_tailoring.model import ResumeDocument
from app.core.resume_tailoring.pdf_layout import build_document
from app.core.storage import StorageService, get_storage
from app.models.application import Application
from app.models.job import Job
from app.models.resume import Resume
from app.schemas.ats import (
    ApplicationScoreItem,
    JobScoreItem,
    MatchSummary,
    ScoredWith,
    TierSummary,
)

logger = structlog.get_logger(__name__)

#: A posting shorter than this has nothing to score against.
_MIN_POSTING_CHARS = 60


@dataclass
class LoadedResume:
    resume: Resume
    doc: ResumeDocument
    pdf: str | None
    parsing: ParsingReport


class ResumeLoader:
    """Reads résumés from storage once per request and remembers them."""

    def __init__(self, user_id: str) -> None:
        self._storage = StorageService(get_storage(), user_id)
        self._cache: dict[str, LoadedResume | None] = {}
        self._temps: list[str] = []

    async def load(self, resume: Resume) -> LoadedResume | None:
        if resume.id in self._cache:
            return self._cache[resume.id]
        loaded = await self._load(resume)
        self._cache[resume.id] = loaded
        return loaded

    async def _load(self, resume: Resume) -> LoadedResume | None:
        doc: ResumeDocument | None = None
        pdf: str | None = None
        # The PDF is what a recruiter's system actually reads, so it is preferred whenever there is
        # one.
        if resume.file_path_pdf:
            try:
                pdf = await self._storage.materialize_to_temp(resume.file_path_pdf, suffix=".pdf")
                self._temps.append(pdf)
                doc = await asyncio.to_thread(build_document, pdf)
            except Exception:
                logger.warning("ats_resume_pdf_unreadable", resume_id=resume.id)
                doc = pdf = None
        if doc is None and resume.file_path_docx:
            try:
                local = await self._storage.materialize_to_temp(
                    resume.file_path_docx, suffix=".docx"
                )
                self._temps.append(local)
                doc = await asyncio.to_thread(extract_from_docx, local)
            except Exception:
                logger.warning("ats_resume_docx_unreadable", resume_id=resume.id)
        if doc is None and (resume.content_text or "").strip():
            doc = parse_resume_text(resume.content_text or "", source_format="text")
        if doc is None or not doc.all_lines():
            return None
        report = await asyncio.to_thread(parsing_report, doc, analyse(doc), pdf)
        return LoadedResume(resume, doc, pdf, report)

    def close(self) -> None:
        for path in self._temps:
            with contextlib.suppress(OSError):
                os.remove(path)
        self._temps.clear()


def job_text(job: Job) -> str:
    """The posting as text: its description plus any structured skills the source supplied."""
    parts = [(job.description or "").strip()]
    skills = job.skills_required if isinstance(job.skills_required, dict) else {}
    required = [str(s) for s in (skills.get("required") or skills.get("skills") or []) if s]
    preferred = [str(s) for s in (skills.get("preferred") or []) if s]
    if required:
        parts.append("Requirements\n" + "\n".join(required))
    if preferred:
        parts.append("Nice to have\n" + "\n".join(preferred))
    return "\n\n".join(p for p in parts if p)


def usable_posting(job: Job) -> bool:
    return len(job_text(job)) >= _MIN_POSTING_CHARS


async def evaluate_pair(loaded: LoadedResume, job: Job) -> Evaluation:
    return await asyncio.to_thread(
        evaluate, loaded.doc, job_text(job), job.title or "", pdf=loaded.pdf, parsing=loaded.parsing
    )


def summarise(ev: Evaluation) -> MatchSummary:
    return MatchSummary(
        ats_match=round(ev.ats_match / 100, 4),
        parsing=round(ev.parsing / 100, 4),
        shortlist=round(ev.shortlist / 100, 4),
        band=ev.band,
        shortlist_band=ev.shortlist_band,
        tiers={
            k: TierSummary(matched=v.matched, mentioned=v.mentioned, total=v.total)
            for k, v in ev.tiers.items()
        },
        top_gaps=[f.requirement for f in ev.missing if f.tier == "critical"][:5],
        constrained_by=ev.constrained_by[:5],
        recruiter_signal=ev.recruiter.signal,
        tailoring_limit=ev.verdict.tailoring_limit,
    )


async def candidate_resumes(db: AsyncSession) -> list[Resume]:
    """The user's live base résumés: what a new application could be tailored from."""
    rows = (
        (
            await db.execute(
                select(Resume)
                .where(Resume.archived_at.is_(None), Resume.type == "base")
                .order_by(Resume.created_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def best_for_job(
    loader: ResumeLoader, resumes: list[Resume], job: Job
) -> tuple[LoadedResume, Evaluation] | None:
    """The base résumé that matches ``job`` best, with its evaluation."""
    best: tuple[LoadedResume, Evaluation] | None = None
    for resume in resumes:
        loaded = await loader.load(resume)
        if loaded is None:
            continue
        ev = await evaluate_pair(loaded, job)
        if best is None or ev.ats_match > best[1].ats_match:
            best = (loaded, ev)
    return best


def _scored_with(loaded: LoadedResume, source: str) -> ScoredWith:
    return ScoredWith(resume_id=loaded.resume.id, resume_name=loaded.resume.name, source=source)


async def score_jobs(
    db: AsyncSession,
    user_id: str,
    job_ids: list[str],
    *,
    resume_id: str | None = None,
    force: bool = False,
) -> list[JobScoreItem]:
    """Score jobs with the best-matching base résumé (or ``resume_id``) and persist "
    "``match_score``."""
    jobs = (await db.execute(select(Job).where(Job.id.in_(job_ids)))).scalars().all()
    by_id = {j.id: j for j in jobs}
    loader = ResumeLoader(user_id)
    items: list[JobScoreItem] = []
    try:
        if resume_id:
            chosen = (
                await db.execute(select(Resume).where(Resume.id == resume_id))
            ).scalar_one_or_none()
            pool = [chosen] if chosen is not None else []
        else:
            pool = await candidate_resumes(db)
        for job_id in job_ids:
            job = by_id.get(job_id)
            if job is None:
                items.append(JobScoreItem(job_id=job_id, scored=False, reason="Job not found"))
                continue
            if job.match_score is not None and not force and not resume_id:
                items.append(JobScoreItem(job_id=job_id, scored=True, match_score=job.match_score))
                continue
            if not usable_posting(job):
                items.append(
                    JobScoreItem(
                        job_id=job_id,
                        scored=False,
                        reason="This posting has no description to score against",
                    )
                )
                continue
            if not pool:
                items.append(
                    JobScoreItem(
                        job_id=job_id, scored=False, reason="Upload a résumé to see a match score"
                    )
                )
                continue
            best = await best_for_job(loader, pool, job)
            if best is None:
                items.append(
                    JobScoreItem(job_id=job_id, scored=False, reason="The résumé could not be read")
                )
                continue
            loaded, ev = best
            job.match_score = round(ev.ats_match / 100, 4)
            items.append(
                JobScoreItem(
                    job_id=job_id,
                    scored=True,
                    match_score=job.match_score,
                    scored_with=_scored_with(loaded, "chosen" if resume_id else "best"),
                    top_gaps=[f.requirement for f in ev.missing if f.tier == "critical"][:3],
                )
            )
        await db.commit()
    finally:
        loader.close()
    return items


async def score_applications(
    db: AsyncSession,
    user_id: str,
    application_ids: list[str] | None,
    *,
    resume_id: str | None = None,
) -> list[ApplicationScoreItem]:
    """Score applications; persist the score where it is the application's own résumé's."""
    query = select(Application)
    if application_ids:
        query = query.where(Application.id.in_(application_ids))
    else:
        query = query.where(Application.status == "pending_review")
    apps = (await db.execute(query)).scalars().all()
    jobs = {
        j.id: j
        for j in (
            await db.execute(select(Job).where(Job.id.in_({a.job_id for a in apps} or {"-"})))
        )
        .scalars()
        .all()
    }
    attached = {
        r.id: r
        for r in (
            await db.execute(
                select(Resume).where(
                    Resume.id.in_({a.resume_id for a in apps if a.resume_id} or {"-"})
                )
            )
        )
        .scalars()
        .all()
    }
    loader = ResumeLoader(user_id)
    items: list[ApplicationScoreItem] = []
    try:
        chosen = None
        if resume_id:
            chosen = (
                await db.execute(select(Resume).where(Resume.id == resume_id))
            ).scalar_one_or_none()
        bases = await candidate_resumes(db)
        for app in apps:
            job = jobs.get(app.job_id)
            if job is None or not usable_posting(job):
                items.append(
                    ApplicationScoreItem(
                        application_id=app.id,
                        job_id=app.job_id,
                        scored=False,
                        reason="This posting has no description to score against",
                    )
                )
                continue
            source, resume = (
                ("chosen", chosen) if chosen else ("attached", attached.get(app.resume_id or ""))
            )
            loaded: LoadedResume | None = None
            ev: Evaluation | None = None
            if resume is not None:
                loaded = await loader.load(resume)
                ev = await evaluate_pair(loaded, job) if loaded else None
            else:
                best = await best_for_job(loader, bases, job)
                source = "best"
                if best:
                    loaded, ev = best
            if loaded is None or ev is None:
                items.append(
                    ApplicationScoreItem(
                        application_id=app.id,
                        job_id=app.job_id,
                        scored=False,
                        reason="Upload a résumé to see a match score"
                        if not bases
                        else "The résumé could not be read",
                    )
                )
                continue
            persisted = False
            if source == "attached":
                # Only the application's own résumé's score is the application's score: the policy
                # that gates auto-apply reads this column, so a hypothetical résumé must not set it.
                app.ats_score = round(ev.ats_match / 100, 4)
                persisted = True
            items.append(
                ApplicationScoreItem(
                    application_id=app.id,
                    job_id=app.job_id,
                    scored=True,
                    ats_score=round(ev.ats_match / 100, 4),
                    persisted=persisted,
                    scored_with=_scored_with(loaded, source),
                    summary=summarise(ev),
                )
            )
        await db.commit()
    finally:
        loader.close()
    return items
