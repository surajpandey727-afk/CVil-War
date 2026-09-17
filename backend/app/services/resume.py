"""Resume management service.

Handles upload, listing, generation, and scoring of resumes.
Uses DocumentParser for real file parsing and SkillMatcher for skill extraction.
"""

import asyncio
import contextlib
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import UploadFile
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.documents.generator import DocumentGenerator
from app.core.documents.parser import DocumentParser, ParsedResume
from app.core.exceptions import ParseError, RecordNotFoundError
from app.core.llm.factory import build_llm_client_for_user
from app.core.storage import StorageService, get_storage, keys
from app.core.storage.documents import (
    DOCX_CONTENT_TYPE,
    PDF_CONTENT_TYPE,
    persist_generated_document,
)
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.resume import Resume
from app.models.user_settings import UserSettings
from app.schemas.resume import (
    ExtractedProfileData,
    ExtractProfileResponse,
    ResumeDeleteResponse,
    ResumeGenerateRequest,
    ResumeListResponse,
    ResumeResponse,
    ResumeScoreRequest,
    ResumeScoreResponse,
    ResumeUploadResponse,
    ResumeUsageItem,
    ResumeUsageResponse,
)

logger = structlog.get_logger(__name__)

# Scratch space for parsing only — the persisted copy goes through StorageService below.
# A project-relative path (the old "data/uploads") lives inside the deployment bundle, which
# is read-only on Vercel; the OS temp dir is the one location guaranteed writable everywhere
# (matches STORAGE__LOCAL_ROOT's own /tmp default for the same reason).
UPLOAD_DIR = Path(tempfile.gettempdir()) / "cvilwar-uploads"

_parser = DocumentParser()


def _extract_skills_text_based(text: str) -> list[str]:
    """Extract skills using the SkillMatcher text-based approach.

    Falls back gracefully if spaCy is not available by using only
    the regex-based word matching in SkillMatcher.extract_skills.
    """
    try:
        from app.core.ats.skill_matcher import SKILL_VARIATIONS

        lower = text.lower()
        import re

        found: list[str] = []
        seen: set[str] = set()
        for canonical, variations in SKILL_VARIATIONS.items():
            if canonical in seen:
                continue
            if re.search(rf"\b{re.escape(canonical)}\b", lower):
                found.append(canonical)
                seen.add(canonical)
                continue
            for variant in variations:
                if re.search(rf"\b{re.escape(variant)}\b", lower):
                    found.append(canonical)
                    seen.add(canonical)
                    break
        return found
    except Exception:
        logger.warning("skill_extraction_fallback_failed")
        return []


def _extract_skills(text: str) -> list[str]:
    """Extract skills, trying spaCy-backed SkillMatcher first, then text-only."""
    try:
        from app.core.ats.nlp import get_nlp
        from app.core.ats.skill_matcher import SkillMatcher

        matcher = SkillMatcher(get_nlp())
        return sorted(matcher.extract_skills(text))
    except Exception:
        logger.info("spacy_unavailable_using_text_extraction")
        return _extract_skills_text_based(text)


async def upload_resume(
    db: AsyncSession,
    file: UploadFile,
    user_id: str,
) -> ResumeUploadResponse:
    """Upload, parse, and store a resume file.

    Saves the file to disk, parses it with DocumentParser to extract
    text, then uses SkillMatcher for skill detection.

    Args:
        db: Async database session.
        file: Uploaded resume file.

    Returns:
        Upload response with detected metadata.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    file_ext = Path(file.filename or "resume.pdf").suffix.lower()
    file_id = uuid.uuid4().hex
    dest = UPLOAD_DIR / f"{file_id}{file_ext}"

    content = await file.read()
    dest.write_bytes(content)

    # Parse the document for real text extraction
    parsed_text = ""
    word_count = 0
    skills_detected: list[str] = []

    try:
        parsed: ParsedResume = await _parser.parse(dest)
        parsed_text = parsed.raw_text
        word_count = parsed.word_count
        skills_detected = _extract_skills(parsed_text)
        logger.info(
            "resume_parsed_successfully",
            file=file.filename,
            word_count=word_count,
            skills_count=len(skills_detected),
        )
    except (ParseError, Exception) as exc:
        # Parsing failed -- still save the record but with raw byte-decoded text
        logger.warning(
            "resume_parse_failed_using_fallback",
            file=file.filename,
            error=str(exc),
        )
        parsed_text = content.decode("utf-8", errors="ignore")
        word_count = len(parsed_text.split())
        # Try skill extraction on the raw text anyway
        skills_detected = _extract_skills(parsed_text)

    # Move the upload into per-tenant storage (the column holds the storage key, not the
    # local temp path); then drop the temp file used only for parsing.
    upload_key = keys.upload_key(user_id, file_id, file_ext.lstrip("."))
    content_type = PDF_CONTENT_TYPE if file_ext == ".pdf" else DOCX_CONTENT_TYPE
    await StorageService(get_storage(), user_id).put(upload_key, content, content_type=content_type)
    with contextlib.suppress(OSError):
        dest.unlink()

    resume = Resume(
        user_id=user_id,
        name=file.filename or "Untitled Resume",
        type="base",
        template_id="modern",
        file_path_pdf=upload_key if file_ext == ".pdf" else None,
        file_path_docx=upload_key if file_ext == ".docx" else None,
        # Full extracted text, not a truncated prefix: a 5000-char cap silently dropped
        # anything past ~1.5 pages, so every later score/tailor operation worked from a
        # partial resume without any indication that content was missing.
        content_text=parsed_text,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    logger.info("resume_uploaded", resume_id=resume.id, filename=file.filename)

    return ResumeUploadResponse(
        id=resume.id,
        name=resume.name,
        file_format=file_ext.lstrip("."),
        word_count=word_count,
        skills_detected=skills_detected,
    )


async def list_resumes(
    db: AsyncSession, *, include_archived: bool = False
) -> ResumeListResponse:
    """List résumés with how often each has been used.

    Archived résumés are held back by default but counted, so the UI can offer to show them
    instead of leaving the user to wonder where a CV went. The usage counts are a single
    grouped query rather than one per row — a user with twenty CVs would otherwise pay twenty
    round trips to render a list.

    Args:
        db: Async database session.
        include_archived: Also return CVs archived after being sent to an employer.

    Returns:
        Résumés with total and archived counts.
    """
    result = await db.execute(select(Resume).order_by(Resume.created_at.desc()))
    resumes = list(result.scalars().all())

    usage_rows = (
        await db.execute(
            select(
                Application.resume_id,
                func.count().label("total"),
                func.sum(
                    case((Application.status.in_(_SENT_STATUSES), 1), else_=0)
                ).label("submitted"),
            )
            .where(Application.resume_id.isnot(None))
            .group_by(Application.resume_id)
        )
    ).all()
    usage = {row.resume_id: (row.total, int(row.submitted or 0)) for row in usage_rows}

    archived_count = sum(1 for r in resumes if r.archived_at is not None)
    visible = resumes if include_archived else [r for r in resumes if r.archived_at is None]

    items = []
    for resume in visible:
        item = ResumeResponse.model_validate(resume)
        item.used_in_applications, item.submitted_applications = usage.get(resume.id, (0, 0))
        items.append(item)
    return ResumeListResponse(
        items=items, total=len(items), archived_count=archived_count
    )


async def get_resume(db: AsyncSession, resume_id: str) -> Resume:
    """Get a resume by ID or raise RecordNotFoundError."""
    result = await db.execute(select(Resume).where(Resume.id == resume_id))
    resume = result.scalar_one_or_none()
    if resume is None:
        raise RecordNotFoundError("Resume", resume_id)
    return resume


async def _get_job(db: AsyncSession, job_id: str) -> Job:
    """Get a job by ID or raise RecordNotFoundError."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise RecordNotFoundError("Job", job_id)
    return job


def _build_resume_data_from_text(content_text: str) -> dict:
    """Convert raw resume text into structured data for templates.

    Extracts contact info, sections, and skills from plain text using
    the same regex patterns as DocumentParser.
    """
    from app.core.documents.parser import (
        _EMAIL_RE,
        _GITHUB_RE,
        _LINKEDIN_RE,
        _PHONE_RE,
        _SECTION_HEADERS,
    )

    lines = content_text.split("\n")
    name = lines[0].strip() if lines else ""

    # Extract contact info
    email_m = _EMAIL_RE.search(content_text)
    phone_m = _PHONE_RE.search(content_text)
    linkedin_m = _LINKEDIN_RE.search(content_text)
    github_m = _GITHUB_RE.search(content_text)

    # Extract sections by header
    sections: dict[str, str] = {}
    current_section = ""
    current_content: list[str] = []
    lower_headers = {h.lower() for h in _SECTION_HEADERS}

    for line in lines[1:]:
        stripped = line.strip()
        if stripped.lower().rstrip(":") in lower_headers:
            if current_section:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = stripped.lower().rstrip(":")
            current_content = []
        elif current_section:
            current_content.append(stripped)

    if current_section:
        sections[current_section] = "\n".join(current_content).strip()

    # Build skills list
    skills_text = sections.get("skills", "") or sections.get("technical skills", "")
    skills = [s.strip() for s in re.split(r"[,\n•·|]", skills_text) if s.strip()]

    # Build experience entries
    exp_text = (
        sections.get("experience", "")
        or sections.get("work experience", "")
        or sections.get("professional experience", "")
    )
    experience = _parse_experience_section(exp_text) if exp_text else []

    # Build education entries
    edu_text = sections.get("education", "") or sections.get("academic background", "")
    education = _parse_education_section(edu_text) if edu_text else []

    # Certifications
    cert_text = sections.get("certifications", "") or sections.get("certificates", "")
    certifications = [c.strip() for c in cert_text.split("\n") if c.strip()] if cert_text else []

    summary = (
        sections.get("summary", "")
        or sections.get("professional summary", "")
        or sections.get("objective", "")
        or sections.get("profile", "")
    )

    return {
        "name": name,
        "email": email_m.group() if email_m else "",
        "phone": phone_m.group() if phone_m else "",
        "location": "",
        "linkedin": linkedin_m.group() if linkedin_m else "",
        "github": github_m.group() if github_m else "",
        "title": "",
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
        "certifications": certifications,
        "projects": [],
    }


def _parse_experience_section(text: str) -> list[dict]:
    """Parse experience section text into structured entries."""
    entries: list[dict] = []
    current: dict | None = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Heuristic: lines that look like titles (short, no bullet)
        if not stripped.startswith(("•", "-", "*", "·")) and len(stripped) < 80:
            if current:
                entries.append(current)
            current = {
                "title": stripped,
                "company": "",
                "duration": "",
                "description": "",
            }
        elif current:
            current["description"] += stripped.lstrip("•-*· ") + "\n"

    if current:
        entries.append(current)
    return entries


def _parse_education_section(text: str) -> list[dict]:
    """Parse education section text into structured entries."""
    entries: list[dict] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith(("•", "-", "*")):
            continue
        entries.append({
            "degree": stripped,
            "institution": "",
            "year": "",
        })
    return entries


async def generate_tailored_resume(
    db: AsyncSession,
    request: ResumeGenerateRequest,
    user_id: str,
) -> ResumeResponse:
    """Generate a tailored resume for a specific job using LLM.

    Loads the base resume and target job, tailors the content via LLM,
    renders to PDF/DOCX, and stores the result.

    Args:
        db: Async database session.
        request: Generation parameters (base_resume_id, job_id, template, formats).

    Returns:
        The generated tailored resume response.
    """
    base = await get_resume(db, request.base_resume_id)
    job = await _get_job(db, request.job_id)

    # Build structured data from base resume text
    resume_data = _build_resume_data_from_text(base.content_text or "")

    # Generate via DocumentGenerator (LLM tailoring + rendering)
    llm = await build_llm_client_for_user(db, user_id)
    generator = DocumentGenerator(llm_client=llm)
    doc = await generator.generate_resume(
        resume_data=resume_data,
        job_description=job.description or "",
        template_name=request.template_id,
        formats=request.output_formats,
    )

    # Move rendered files into per-tenant storage; columns hold the storage keys.
    pdf_key, docx_key = await persist_generated_document(user_id, doc)

    # Create the tailored resume record
    tailored = Resume(
        user_id=user_id,
        name=f"Tailored - {base.name}",
        type="tailored",
        template_id=request.template_id,
        base_resume_id=request.base_resume_id,
        job_id=request.job_id,
        file_path_pdf=pdf_key,
        file_path_docx=docx_key,
        content_text=base.content_text,
    )
    db.add(tailored)
    await db.commit()
    await db.refresh(tailored)

    logger.info(
        "tailored_resume_generated",
        resume_id=tailored.id,
        base_id=request.base_resume_id,
        job_id=request.job_id,
        has_pdf=doc.pdf_path is not None,
        has_docx=doc.docx_path is not None,
    )
    return ResumeResponse.model_validate(tailored)


async def score_resume(
    db: AsyncSession,
    resume_id: str,
    request: ResumeScoreRequest,
) -> ResumeScoreResponse:
    """Score a resume against a job listing using multi-factor ATS analysis.

    Loads the resume text and job description from the database, then
    uses ResumeScorer for real scoring. Falls back to a basic keyword
    overlap score if spaCy is not available.

    Args:
        db: Async database session.
        resume_id: UUID of the resume.
        request: Scoring request with target job ID.

    Returns:
        Detailed ATS score breakdown.
    """
    resume = await get_resume(db, resume_id)
    job = await _get_job(db, request.job_id)

    resume_text = resume.content_text or ""
    job_description = job.description or ""

    if not resume_text.strip():
        logger.warning("score_resume_empty_text", resume_id=resume_id)
        return ResumeScoreResponse(
            resume_id=resume_id,
            job_id=request.job_id,
            overall_score=0.0,
            skill_score=0.0,
            experience_score=0.0,
            education_score=0.0,
            keyword_score=0.0,
            missing_skills=["Resume has no parsed text content"],
            suggestions=["Re-upload your resume to enable parsing"],
        )

    # The candidate's structured work history/education — set up once in Settings, not
    # re-derived from the resume file each time. Without this, experience_score and
    # education_score were computed against permanently-empty lists (see the two bugs this
    # replaces below): every résumé scored a flat 0.0 on experience and an arbitrary 0.2/1.0
    # on education, regardless of which job or which résumé — the "multi-factor" score's other
    # two factors, 50% of the total weight, were pure noise.
    settings_row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == resume.user_id))
    ).scalar_one_or_none()
    profile = (settings_row.candidate_profile or {}) if settings_row else {}
    candidate_experience = _experience_entries_for_scoring(profile.get("experience") or [])
    candidate_education = _education_entries_for_scoring(profile.get("education") or [])

    try:
        # Offload the synchronous, CPU-bound spaCy scoring to a thread so it never blocks the
        # event loop (the cached model in core.ats.nlp keeps the load cost one-time).
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _score_with_full_engine,
            resume_id,
            request.job_id,
            resume_text,
            job_description,
            job,
            candidate_experience,
            candidate_education,
        )
    except Exception as exc:
        logger.warning(
            "full_scoring_failed_using_fallback",
            error=str(exc),
        )
        return _score_with_text_fallback(
            resume_id, request.job_id, resume_text, job_description,
        )


def _parse_year(date_text: str) -> int | None:
    """Best-effort 4-digit year out of a free-text date field ("Jan 2020", "2020-01")."""
    match = re.search(r"(19|20)\d{2}", date_text or "")
    return int(match.group(0)) if match else None


def _experience_entries_for_scoring(raw: list[dict]) -> list[dict[str, object]]:
    """Convert stored ``WorkExperienceSchema`` entries into what ExperienceAnalyzer expects.

    ``duration_years`` is not stored directly — the schema records ``start_date``/``end_date``
    as free text (whatever the operator typed) — so it is derived here from whichever 4-digit
    year each field contains. An open-ended entry ("Present", blank) counts through the
    current year rather than being dropped, since ongoing roles are exactly the ones that
    should count most toward total experience.
    """
    entries: list[dict[str, object]] = []
    current_year = datetime.now(UTC).year
    for item in raw:
        if not isinstance(item, dict):
            continue
        start_year = _parse_year(str(item.get("start_date", "")))
        if start_year is None:
            continue  # no usable start date — cannot derive a duration for this entry
        end_text = str(item.get("end_date", "")).strip().lower()
        end_year = current_year if end_text in ("", "present", "current", "ongoing") else (
            _parse_year(end_text) or current_year
        )
        entries.append({
            "title": item.get("title", ""),
            "company": item.get("company", ""),
            "description": item.get("description", ""),
            "responsibilities": item.get("responsibilities") or [],
            "duration_years": max(0.0, end_year - start_year),
        })
    return entries


def _education_entries_for_scoring(raw: list[dict]) -> list[dict[str, object]]:
    """Convert stored ``EducationSchema`` entries into what ``_score_education`` expects."""
    return [
        {"degree": item.get("degree", ""), "institution": item.get("institution", "")}
        for item in raw
        if isinstance(item, dict)
    ]


async def extract_candidate_profile_from_resume(
    db: AsyncSession, resume_id: str, user_id: str,
) -> ExtractProfileResponse:
    """Read one résumé's text with an LLM and fill in the account's work history/education.

    Built because the ATS score's experience and education factors need real structured data
    to score against, and nothing populated it — a résumé upload only ever extracted plain
    text (see ``core.documents.parser``), so every score computed those two factors against a
    permanently empty list until the operator hand-typed their entire career history into
    Settings. This reads a résumé they already uploaded instead.

    Never overwrites an existing profile: if ``candidate_profile.experience`` already has
    entries, this is a no-op (``profile_updated=False``) — a second résumé should not silently
    replace history the operator (or an earlier extraction) already established. Delete the
    stored entries in Settings first to re-run this against a different résumé.
    """
    resume = await get_resume(db, resume_id)
    resume_text = resume.content_text or ""
    if not resume_text.strip():
        return ExtractProfileResponse(
            resume_id=resume_id, experience_found=0, education_found=0,
            profile_updated=False, detail="Résumé has no parsed text content.",
        )

    settings_row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    if settings_row is None:
        settings_row = UserSettings(user_id=user_id)
        db.add(settings_row)
        await db.flush()

    existing_profile = settings_row.candidate_profile or {}
    if existing_profile.get("experience"):
        return ExtractProfileResponse(
            resume_id=resume_id,
            experience_found=len(existing_profile["experience"]),
            education_found=len(existing_profile.get("education") or []),
            profile_updated=False,
            detail="Candidate profile already has work history — left unchanged.",
        )

    from app.core.llm.prompts.profile_extract import (
        PROFILE_EXTRACT_SYSTEM_PROMPT,
        render_profile_extract_prompt,
    )

    llm = await build_llm_client_for_user(db, user_id)
    extracted = await llm.complete_with_structured_output(
        prompt=render_profile_extract_prompt(resume_text),
        output_schema=ExtractedProfileData,
        system_prompt=PROFILE_EXTRACT_SYSTEM_PROMPT,
        purpose="profile_extract",
    )

    settings_row.candidate_profile = {
        **existing_profile,
        "experience": [e.model_dump() for e in extracted.experience],
        "education": [e.model_dump() for e in extracted.education],
    }
    await db.commit()
    logger.info(
        "profile_extracted_from_resume", resume_id=resume_id, user_id=user_id,
        experience_found=len(extracted.experience), education_found=len(extracted.education),
    )
    return ExtractProfileResponse(
        resume_id=resume_id,
        experience_found=len(extracted.experience),
        education_found=len(extracted.education),
        profile_updated=True,
        detail="Candidate profile updated from this résumé.",
    )


def _score_with_full_engine(
    resume_id: str,
    job_id: str,
    resume_text: str,
    job_description: str,
    job: Job,
    candidate_experience: list[dict[str, object]],
    candidate_education: list[dict[str, object]],
) -> ResumeScoreResponse:
    """Score using the full ResumeScorer with spaCy."""
    from app.core.ats.experience_analyzer import ExperienceAnalyzer
    from app.core.ats.keyword_analyzer import KeywordAnalyzer
    from app.core.ats.nlp import get_nlp
    from app.core.ats.scorer import ResumeScorer
    from app.core.ats.skill_matcher import SkillMatcher

    nlp = get_nlp()
    skill_matcher = SkillMatcher(nlp)
    keyword_analyzer = KeywordAnalyzer(nlp)
    experience_analyzer = ExperienceAnalyzer(nlp)
    scorer = ResumeScorer(skill_matcher, keyword_analyzer, experience_analyzer)

    # Build candidate profile from resume text plus the operator's own structured profile
    # (Settings > Candidate profile) for the two dimensions a resume file alone cannot supply
    # reliable structured data for.
    candidate_skills = sorted(skill_matcher.extract_skills(resume_text))
    candidate_profile = {
        "skills": candidate_skills,
        "experience": candidate_experience,
        "education": candidate_education,
    }

    # Build job metadata from the Job model
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    if job.skills_required and isinstance(job.skills_required, dict):
        required_skills = job.skills_required.get("required", [])
        preferred_skills = job.skills_required.get("preferred", [])
    job_metadata = {
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
    }

    details = scorer.score_resume(
        resume_text, job_description, candidate_profile, job_metadata,
    )

    return ResumeScoreResponse(
        resume_id=resume_id,
        job_id=job_id,
        overall_score=details.overall_score,
        skill_score=details.skill_score,
        experience_score=details.experience_score,
        education_score=details.education_score,
        keyword_score=details.keyword_score,
        missing_skills=details.missing_required_skills,
        suggestions=details.improvement_suggestions,
    )


def _score_with_text_fallback(
    resume_id: str,
    job_id: str,
    resume_text: str,
    job_description: str,
) -> ResumeScoreResponse:
    """Basic keyword overlap scoring when spaCy is unavailable."""
    resume_skills = set(_extract_skills(resume_text))
    job_skills = set(_extract_skills(job_description))

    if job_skills:
        matched = resume_skills & job_skills
        skill_score = len(matched) / len(job_skills)
        missing = sorted(job_skills - resume_skills)
    else:
        skill_score = 0.5
        missing = []

    # Simple keyword overlap
    resume_words = set(resume_text.lower().split())
    job_words = set(job_description.lower().split()) - {
        "the", "a", "an", "is", "are", "and", "or", "to", "in", "of", "for",
        "with", "on", "at", "by", "from", "as", "we", "you", "your", "our",
    }
    keyword_score = len(resume_words & job_words) / len(job_words) if job_words else 0.0

    overall = 0.5 * skill_score + 0.5 * min(keyword_score, 1.0)

    suggestions: list[str] = []
    if missing:
        suggestions.append(
            f"Add these skills to your resume: {', '.join(missing[:5])}"
        )
    if keyword_score < 0.4:
        suggestions.append(
            "Mirror more terminology from the job description in your resume."
        )

    return ResumeScoreResponse(
        resume_id=resume_id,
        job_id=job_id,
        overall_score=round(overall, 4),
        skill_score=round(skill_score, 4),
        experience_score=0.0,
        education_score=0.0,
        keyword_score=round(min(keyword_score, 1.0), 4),
        missing_skills=missing,
        suggestions=suggestions,
    )


async def optimize_resume(
    db: AsyncSession,
    resume_id: str,
    user_id: str,
    job_id: str | None = None,
) -> ResumeResponse:
    """Optimize a resume for ATS compatibility using LLM rewriting.

    Scores the resume, gets improvement suggestions, then uses the LLM
    to rewrite the content for maximum ATS pass-through. Creates a new
    optimized resume record linked to the original.

    Args:
        db: Async database session.
        resume_id: ID of the resume to optimize.
        job_id: Target job ID. Falls back to resume.job_id if absent.

    Returns:
        The newly created optimized resume.
    """
    resume = await get_resume(db, resume_id)
    target_job_id = job_id or resume.job_id
    if not target_job_id:
        raise RecordNotFoundError("Job", "none (no job_id provided)")

    job = await _get_job(db, target_job_id)
    resume_text = resume.content_text or ""
    job_description = job.description or ""

    # Score the resume to get detailed breakdown
    score_result = await score_resume(
        db, resume_id, ResumeScoreRequest(job_id=target_job_id),
    )

    # Get optimizer suggestions
    score_breakdown = {
        "overall_score": score_result.overall_score,
        "skill_score": score_result.skill_score,
        "experience_score": score_result.experience_score,
        "education_score": score_result.education_score,
        "keyword_score": score_result.keyword_score,
        "missing_skills": score_result.missing_skills,
    }

    try:
        from app.core.ats.nlp import get_nlp
        from app.core.ats.optimizer import ATSOptimizer
        from app.core.ats.skill_matcher import SkillMatcher

        optimizer = ATSOptimizer(skill_matcher=SkillMatcher(get_nlp()))
        from app.core.ats.scorer import ScoreDetails
        # Build a minimal ScoreDetails for the optimizer
        details = ScoreDetails(
            overall_score=score_result.overall_score,
            skill_score=score_result.skill_score,
            experience_score=score_result.experience_score,
            education_score=score_result.education_score,
            keyword_score=score_result.keyword_score,
            missing_required_skills=score_result.missing_skills,
            improvement_suggestions=score_result.suggestions,
        )
        suggestions = optimizer.suggest_improvements(
            details, resume_text, job_description,
        )
    except Exception:
        logger.warning("ats_optimizer_unavailable", exc_info=True)
        suggestions = score_result.suggestions

    # Use LLM to rewrite the resume
    from app.core.llm.prompts.ats_optimize import (
        ATS_OPTIMIZE_SYSTEM_PROMPT,
        render_ats_optimize_prompt,
    )
    from app.core.llm.prompts.resume_tailor import TailoredResumeData

    llm = await build_llm_client_for_user(db, user_id)
    prompt = render_ats_optimize_prompt(
        resume_text, job_description, score_breakdown, suggestions,
    )
    optimized_data = await llm.complete_with_structured_output(
        prompt=prompt,
        output_schema=TailoredResumeData,
        system_prompt=ATS_OPTIMIZE_SYSTEM_PROMPT,
        purpose="ats_optimize",
    )

    # Render optimized resume to PDF/DOCX
    generator = DocumentGenerator(llm_client=None)
    doc = await generator.generate_resume(
        resume_data=optimized_data.model_dump(),
        job_description="",
        template_name=resume.template_id,
        formats=["pdf", "docx"],
    )

    pdf_key, docx_key = await persist_generated_document(user_id, doc)

    # Create new optimized resume record
    optimized = Resume(
        user_id=user_id,
        name=f"Optimized - {resume.name}",
        type="optimized",
        template_id=resume.template_id,
        base_resume_id=resume_id,
        job_id=target_job_id,
        file_path_pdf=pdf_key,
        file_path_docx=docx_key,
        content_text=resume_text,
    )
    db.add(optimized)
    await db.commit()
    await db.refresh(optimized)

    # Re-score the optimized resume
    try:
        new_score = await score_resume(
            db, optimized.id, ResumeScoreRequest(job_id=target_job_id),
        )
        optimized.ats_score = new_score.overall_score
        await db.commit()
        await db.refresh(optimized)
    except Exception:
        logger.warning("ats_rescore_failed", exc_info=True)

    logger.info(
        "resume_optimized",
        original_id=resume_id,
        optimized_id=optimized.id,
        original_score=score_result.overall_score,
        new_score=optimized.ats_score,
    )
    return ResumeResponse.model_validate(optimized)


#: Statuses in which an application has actually been sent, or is being sent, to an employer.
#: A résumé attached to one of these is a record of what somebody received, not a working
#: file — see ``delete_resume``.
_SENT_STATUSES = (
    ApplicationStatus.APPLYING,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.REJECTED,
    ApplicationStatus.OFFER,
)


async def resume_usage(db: AsyncSession, resume_id: str) -> ResumeUsageResponse:
    """Every application this résumé was attached to, newest first.

    Answers the question the résumé list cannot: not "is this in use" but "where, and did it
    actually go out". A CV attached to a draft is disposable; one attached to a submitted
    application is evidence.
    """
    await get_resume(db, resume_id)  # 404s rather than reporting empty usage for a bad id
    rows = (
        await db.execute(
            select(Application, Job)
            .join(Job, Job.id == Application.job_id)
            .where(Application.resume_id == resume_id)
            .order_by(Application.created_at.desc())
        )
    ).all()
    items = [
        ResumeUsageItem(
            application_id=app.id,
            job_title=job.title,
            company=job.company,
            status=app.status.value,
            submitted=app.status in _SENT_STATUSES,
            applied_at=app.applied_at,
            ats_score=app.ats_score,
        )
        for app, job in rows
    ]
    return ResumeUsageResponse(
        resume_id=resume_id,
        total=len(items),
        submitted=sum(1 for i in items if i.submitted),
        items=items,
    )


async def delete_resume(db: AsyncSession, resume_id: str) -> ResumeDeleteResponse:
    """Delete a résumé, or archive it if an employer has already received it.

    The two cases are genuinely different and the endpoint does not pretend otherwise:

    * **Never submitted** — deleted outright, along with its stored PDF and DOCX. There is
      nothing to preserve, and leaving orphaned files behind is how a storage bucket fills up
      with documents nobody can reach.
    * **Submitted with at least one application** — archived instead. Hard-deleting it would
      set every one of those applications' ``resume_id`` to NULL, so the record of what an
      employer actually received would be silently destroyed. The response says which
      happened and how many applications were involved, so the UI can tell the user rather
      than leaving them to guess why the CV is still visible somewhere.

    Archiving is idempotent: archiving an already-archived résumé is a no-op that reports the
    same counts.
    """
    resume = await get_resume(db, resume_id)
    usage = await resume_usage(db, resume_id)

    if usage.submitted > 0:
        if resume.archived_at is None:
            resume.archived_at = datetime.now(UTC)
            await db.commit()
        logger.info("resume_archived", resume_id=resume_id, used_by=usage.submitted)
        return ResumeDeleteResponse(
            resume_id=resume_id,
            deleted=False,
            archived=True,
            used_by=usage.submitted,
            detail=(
                f"Kept and archived: this CV was sent with {usage.submitted} "
                f"application{'s' if usage.submitted != 1 else ''}, and those records need to "
                "keep showing what the employer actually received. It no longer appears in "
                "your list or in any CV picker."
            ),
        )

    # Unused: remove the stored files first. Doing it after the row is gone would lose the
    # keys on failure and orphan the objects permanently.
    storage = StorageService(get_storage(), resume.user_id)
    for key in (resume.file_path_pdf, resume.file_path_docx):
        if key:
            with contextlib.suppress(Exception):  # a missing object must not block the delete
                await storage.delete(key)

    await db.delete(resume)
    await db.commit()
    logger.info("resume_deleted", resume_id=resume_id)
    return ResumeDeleteResponse(
        resume_id=resume_id,
        deleted=True,
        archived=False,
        used_by=0,
        detail="Deleted, along with its stored files. It had never been sent to an employer.",
    )
