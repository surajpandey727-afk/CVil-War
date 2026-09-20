"""Market signals and job-specific résumé tailoring.

Kept separate from ``services.resume_intelligence`` (plain CRUD/versioning, no LLM, no cost)
because everything in this module either scans the Job table or calls an LLM — the one part
of Resume Intelligence that must never run passively. Market signals are cached on the branch
and only recomputed when stale or explicitly refreshed; tailoring only ever runs when the
operator clicks "Tailor résumé" for one specific job.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LLMError, RecordNotFoundError
from app.core.llm.factory import build_llm_client_for_user
from app.core.llm.prompts.resume_intelligence_tailor import (
    RESUME_TAILOR_SYSTEM_PROMPT,
    render_resume_tailor_prompt,
)
from app.models.enums import LLMPurpose, ResumeChangeStatus, ResumeChangeType, ResumeVersionSource
from app.models.job import Job
from app.models.resume_intelligence import JobResumeAnalysis, ResumeBranch, ResumeChange
from app.schemas.resume_intelligence import (
    ChangeDecision,
    CommitTailorRequest,
    CommitTailorResponse,
    MarketSignalsResponse,
    ProposedChangeOut,
    ResumeContent,
    SkillSignal,
    TailorLLMOutput,
    TailorRequest,
    TailorResponse,
    TitleAnalysisOut,
)
from app.services import resume_intelligence as ri

logger = structlog.get_logger(__name__)

_STALE_AFTER = timedelta(hours=24)
_STOPWORDS = {"the", "a", "an", "of", "and", "or", "for", "in", "at", "to", "with", "-", "–"}
_SENIORITY_WORDS = {
    "senior", "junior", "lead", "principal", "staff", "associate", "entry", "mid", "sr", "jr",
}
_TITLE_OVERLAP_THRESHOLD = 0.6
_MAX_SIGNAL_SKILLS = 25


def _significant_words(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in _STOPWORDS and w not in _SENIORITY_WORDS}


def _title_matches(branch_words: set[str], job_title: str) -> bool:
    if not branch_words:
        return False
    job_words = _significant_words(job_title)
    if not job_words:
        return False
    overlap = branch_words & job_words
    return (len(overlap) / len(branch_words)) >= _TITLE_OVERLAP_THRESHOLD


async def compute_market_signals(
    db: AsyncSession, user_id: str, branch: ResumeBranch, *, force: bool = False,
) -> MarketSignalsResponse:
    """Real skill-frequency stats over this user's own discovered jobs matching the branch's
    role title — never a fabricated percentage (see product requirement). Cached on the branch
    and only recomputed when stale (>24h) or explicitly forced.
    """
    now = datetime.now(UTC)
    if (
        not force and branch.market_signals and branch.market_signals_computed_at
        and now - branch.market_signals_computed_at < _STALE_AFTER
    ):
        signals = {k: SkillSignal(**v) for k, v in branch.market_signals.items()}
        matched = next(iter(signals.values())).total_jobs if signals else 0
        return MarketSignalsResponse(
            branch_id=branch.id, signals=signals, matched_jobs=matched,
            total_jobs_scanned=matched, computed_at=branch.market_signals_computed_at,
        )

    from app.core.ats.skill_matcher import SkillMatcher

    skill_matcher = SkillMatcher(None)
    branch_words = _significant_words(branch.role_name)

    all_jobs = (
        await db.execute(select(Job.title, Job.description, Job.skills_required).where(Job.user_id == user_id))
    ).all()
    matched_rows = [j for j in all_jobs if _title_matches(branch_words, j.title)]

    tally: dict[str, int] = {}
    for _title, description, skills_required in matched_rows:
        skills: set[str] = set()
        if isinstance(skills_required, dict):
            skills |= {s for s in (skills_required.get("required") or []) if isinstance(s, str)}
            skills |= {s for s in (skills_required.get("preferred") or []) if isinstance(s, str)}
        if not skills and description:
            skills |= skill_matcher.extract_skills(description)
        for skill in skills:
            tally[skill] = tally.get(skill, 0) + 1

    total = len(matched_rows)
    top = sorted(tally.items(), key=lambda kv: kv[1], reverse=True)[:_MAX_SIGNAL_SKILLS]
    signals = {
        skill: SkillSignal(
            frequency=round(count / total, 2) if total else 0.0, matched_jobs=count, total_jobs=total,
        )
        for skill, count in top
    }

    branch.market_signals = {k: v.model_dump() for k, v in signals.items()}
    branch.market_signals_computed_at = now
    await db.commit()
    logger.info(
        "resume_intelligence.market_signals_computed", branch_id=branch.id,
        matched_jobs=total, scanned=len(all_jobs),
    )
    return MarketSignalsResponse(
        branch_id=branch.id, signals=signals, matched_jobs=total,
        total_jobs_scanned=len(all_jobs), computed_at=now,
    )


async def _auto_select_branch(db: AsyncSession, user_id: str, job_title: str) -> ResumeBranch:
    result = await db.execute(select(ResumeBranch).where(ResumeBranch.user_id == user_id))
    branches = result.scalars().all()
    if not branches:
        raise RecordNotFoundError(
            "ResumeBranch", "none — create a role branch before tailoring against a job"
        )
    job_words = _significant_words(job_title)
    best, best_score = branches[0], -1.0
    for b in branches:
        branch_words = _significant_words(b.role_name)
        if not branch_words or not job_words:
            continue
        score = len(branch_words & job_words) / len(branch_words | job_words)
        if score > best_score:
            best, best_score = b, score
    return best


async def tailor_job(
    db: AsyncSession, user_id: str, request: TailorRequest,
) -> TailorResponse:
    """The core "Tailor résumé" action: algorithmic skill matching (always available) plus an
    LLM pass for contextual matching, title analysis, and proposed edits (best-effort — a
    reachable-gateway failure degrades to algorithmic-only, never an error the operator can't
    work around). Nothing is applied to any résumé content here; see commit_tailor.
    """
    job = (
        await db.execute(select(Job).where(Job.id == request.job_id, Job.user_id == user_id))
    ).scalar_one_or_none()
    if job is None:
        raise RecordNotFoundError("Job", request.job_id)

    if request.branch_id:
        branch = (
            await db.execute(
                select(ResumeBranch).where(
                    ResumeBranch.id == request.branch_id, ResumeBranch.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if branch is None:
            raise RecordNotFoundError("ResumeBranch", request.branch_id)
    else:
        branch = await _auto_select_branch(db, user_id, job.title)

    base_version = await ri.latest_version(db, user_id, branch_id=branch.id)
    if base_version is None:
        raise RecordNotFoundError("ResumeVersion", f"branch {branch.id} has no version yet")

    from app.core.ats.skill_matcher import SkillMatcher

    skill_matcher = SkillMatcher(None)
    content = base_version.content or {}
    candidate_skills: list[str] = list(content.get("skills") or [])
    achievement_text = " ".join(
        a.get("text", "") for e in (content.get("experience") or []) for a in (e.get("achievements") or [])
    )
    candidate_skills += list(skill_matcher.extract_skills(achievement_text))

    required = []
    preferred = []
    if isinstance(job.skills_required, dict):
        required = [s for s in (job.skills_required.get("required") or []) if isinstance(s, str)]
        preferred = [s for s in (job.skills_required.get("preferred") or []) if isinstance(s, str)]
    if not required and not preferred and job.description:
        required = list(skill_matcher.extract_skills(job.description))

    all_required = list(dict.fromkeys(required + preferred))
    matched = {s: "Listed in your skills/experience" for s in all_required if skill_matcher.has_skill(candidate_skills, s)}
    remaining = [s for s in all_required if s not in matched]

    llm_out: TailorLLMOutput | None = None
    llm_unavailable_note = ""
    try:
        llm = await build_llm_client_for_user(db, user_id)
        llm_out = await llm.complete_with_structured_output(
            prompt=render_resume_tailor_prompt(content, job.title, job.description or ""),
            output_schema=TailorLLMOutput,
            system_prompt=RESUME_TAILOR_SYSTEM_PROMPT,
            purpose=LLMPurpose.RESUME_INTELLIGENCE_TAILOR.value,
        )
    except LLMError as exc:
        logger.warning("resume_tailoring.llm_unavailable", job_id=job.id, error=str(exc))
        llm_unavailable_note = "AI reviewer unavailable — showing algorithmic keyword match only."

    partial: dict[str, str] = {}
    missing: dict[str, str] = {}
    ats_pct: float | None = None
    role_fit_notes = llm_unavailable_note
    positioning_notes = ""
    title_analysis: TitleAnalysisOut | None = None
    proposed_llm_changes: list = []

    if llm_out is not None:
        for skill, evidence in llm_out.contextually_satisfied.items():
            if skill in remaining:
                partial[skill] = evidence
        for skill in remaining:
            if skill not in partial:
                missing[skill] = "No evidence found in résumé content"
        ats_pct = max(0.0, min(100.0, llm_out.ats_alignment_pct))
        role_fit_notes = llm_out.role_fit_notes
        positioning_notes = llm_out.positioning_notes
        ta = llm_out.title_analysis
        current_title = content.get("experience", [{}])[0].get("title", "") if content.get("experience") else ""
        title_analysis = TitleAnalysisOut(
            current_title=ta.current_title or current_title,
            target_title=ta.target_title or job.title,
            relationship=ta.relationship, shared_experience=ta.shared_experience,
            positioning_opportunity=ta.positioning_opportunity,
        )
        proposed_llm_changes = llm_out.proposed_changes
    else:
        missing = {s: "No evidence found in résumé content" for s in remaining}

    analysis = JobResumeAnalysis(
        user_id=user_id, job_id=job.id, branch_id=branch.id, base_version_id=base_version.id,
        matched=matched, partial=partial, missing=missing, unsupported={},
        ats_alignment_pct=ats_pct, role_fit_notes=role_fit_notes, positioning_notes=positioning_notes,
        title_analysis=title_analysis.model_dump() if title_analysis else None,
    )
    db.add(analysis)
    await db.flush()

    proposed_rows: list[ResumeChange] = []
    for change in proposed_llm_changes:
        try:
            change_type = ResumeChangeType(change.change_type)
        except ValueError:
            change_type = ResumeChangeType.MODIFIED
        if not change.evidence.strip() or not change.after_text.strip():
            # Rule 5/6 in the prompt: a change with no cited evidence is not trustworthy
            # enough to even offer for review — dropped rather than shown ungrounded.
            continue
        row = ResumeChange(
            user_id=user_id, analysis_id=analysis.id, version_id=None,
            change_type=change_type, section=change.section or "summary",
            before_text=change.before_text or None, after_text=change.after_text,
            reason=change.reason, source_job_id=job.id, evidence=change.evidence,
            status=ResumeChangeStatus.PROPOSED,
        )
        db.add(row)
        proposed_rows.append(row)
    await db.commit()
    for row in proposed_rows:
        await db.refresh(row)

    return TailorResponse(
        analysis_id=analysis.id, branch_id=branch.id, branch_role_name=branch.role_name,
        base_version_id=base_version.id, matched=matched, partial=partial, missing=missing,
        ats_alignment_pct=ats_pct, role_fit_notes=role_fit_notes, positioning_notes=positioning_notes,
        title_analysis=title_analysis,
        proposed_changes=[
            ProposedChangeOut(
                id=r.id, change_type=str(r.change_type), section=r.section,
                before_text=r.before_text, after_text=r.after_text, reason=r.reason,
                evidence=r.evidence,
            )
            for r in proposed_rows
        ],
    )


def _apply_change_to_content(content: dict, section: str, before: str | None, after: str) -> dict:
    """Best-effort structural application of one accepted change onto a content dict.

    Handles the common cases directly (summary rewrite, skill edit/reorder); an experience or
    projects change only applies when it edits TEXT THE CANDIDATE ALREADY WROTE (``before``
    matches an existing achievement verbatim) — a rewrite of real content, never new content.

    A pure addition to experience/projects (``before`` empty — a brand new bullet the LLM
    drafted from scratch) is deliberately NOT written into the résumé here, even if the
    operator accepted it. The tailoring prompt is instructed to never fabricate an employer,
    date, or achievement, but an LLM can still slip and draft a plausible-sounding placeholder
    (e.g. a synthesized "Company X, 2019-2024" bullet) when the résumé has a claimed-but-absent
    work history — see the incident this guards against: a real run proposed exactly that, the
    operator's single "Commit version" click accepted it by default, and prior code appended it
    verbatim into ``additional``, landing a fabricated employer in a résumé a user could submit.
    The proposal still lands in the change log (the audit trail this feature's Change Log
    exists for), so nothing is silently dropped — the operator sees it and must add real
    experience by hand (or via "Edit") rather than have LLM-authored prose ghostwrite their
    work history.
    """
    if section == "summary":
        content["summary"] = after
        return content
    if section == "skills":
        skills = list(content.get("skills") or [])
        # A "reordered"/whole-list change carries the full comma-joined list in both `before`
        # and `after` (not a single skill) — match that shape first, or the single-skill
        # branch below would wrongly append the entire joined string as one bogus "skill".
        if before and [s.strip() for s in before.split(",")] == skills:
            content["skills"] = [s.strip() for s in after.split(",") if s.strip()]
            return content
        if before and before in skills:
            skills = [after if s == before else s for s in skills]
        elif after not in skills:
            skills.append(after)
        content["skills"] = skills
        return content
    if before:
        for entry in content.get("experience") or []:
            for achievement in entry.get("achievements") or []:
                if achievement.get("text") == before:
                    achievement["text"] = after
                    return content
        for project in content.get("projects") or []:
            for achievement in project.get("achievements") or []:
                if achievement.get("text") == before:
                    achievement["text"] = after
                    return content
    return content


async def commit_tailor(
    db: AsyncSession, user_id: str, analysis_id: str, request: CommitTailorRequest,
) -> CommitTailorResponse:
    """Apply the operator's per-change accept/edit/reject decisions, creating exactly one new
    ResumeVersion from the accepted set — never all changes applied automatically."""
    analysis = (
        await db.execute(
            select(JobResumeAnalysis).where(
                JobResumeAnalysis.id == analysis_id, JobResumeAnalysis.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if analysis is None:
        raise RecordNotFoundError("JobResumeAnalysis", analysis_id)

    proposed = (
        await db.execute(
            select(ResumeChange).where(ResumeChange.analysis_id == analysis_id, ResumeChange.user_id == user_id)
        )
    ).scalars().all()
    by_id = {c.id: c for c in proposed}

    parent = await ri.get_version_row(db, user_id, analysis.base_version_id)
    content = dict(parent.content)
    accepted = 0
    rejected = 0
    decisions_by_id = {d.change_id: d for d in request.decisions}

    for change in proposed:
        decision: ChangeDecision | None = decisions_by_id.get(change.id)
        if decision is None or decision.decision == "reject":
            change.status = ResumeChangeStatus.REJECTED
            rejected += 1
            continue
        final_text = decision.edited_after_text if decision.decision == "edit" and decision.edited_after_text else change.after_text
        content = _apply_change_to_content(content, change.section, change.before_text, final_text or "")
        change.status = ResumeChangeStatus.ACCEPTED
        change.after_text = final_text
        accepted += 1

    branch = await db.get(ResumeBranch, analysis.branch_id)
    label_prefix = branch.role_name if branch else "MAIN"
    new_content = ResumeContent.model_validate(content)
    new_version = await ri.create_version(
        db, user_id, branch_id=analysis.branch_id, content=new_content,
        source=ResumeVersionSource.AI_SUGGESTION,
        commit_message=request.commit_message or f"Tailored for {analysis.job_id}",
        label_prefix=label_prefix, parent=parent,
    )
    for change in proposed:
        if change.status == ResumeChangeStatus.ACCEPTED:
            change.version_id = new_version.id
    analysis.proposed_version_id = new_version.id
    await db.commit()
    await db.refresh(new_version)

    ats_after: float | None = None
    if accepted:
        # Cheap, algorithmic-only re-check (no LLM) — an honest before/after delta the
        # operator can trust immediately, without waiting on or paying for another LLM call.
        from app.core.ats.skill_matcher import SkillMatcher

        skill_matcher = SkillMatcher(None)
        job = await db.get(Job, analysis.job_id)
        if job is not None:
            required = []
            preferred = []
            if isinstance(job.skills_required, dict):
                required = [s for s in (job.skills_required.get("required") or []) if isinstance(s, str)]
                preferred = [s for s in (job.skills_required.get("preferred") or []) if isinstance(s, str)]
            all_required = list(dict.fromkeys(required + preferred))
            if all_required:
                new_skills = list(new_content.skills)
                matched_after = sum(1 for s in all_required if skill_matcher.has_skill(new_skills, s))
                ats_after = round(100 * matched_after / len(all_required), 1)

    return CommitTailorResponse(
        version=ri.version_summary(new_version), accepted_count=accepted, rejected_count=rejected,
        ats_alignment_before=analysis.ats_alignment_pct, ats_alignment_after=ats_after,
    )
