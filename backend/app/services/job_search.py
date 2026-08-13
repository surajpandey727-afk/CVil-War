"""Job search and management service.

Handles job CRUD operations, search orchestration across platform
scrapers, and ATS-based job analysis.
"""

import hashlib
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SUPPORTED_PLATFORMS
from app.config.settings import get_settings
from app.core.automation.platforms import platform_registry
from app.core.automation.platforms.base import JobListing
from app.core.exceptions import RecordNotFoundError
from app.core.job_discovery.exa_search import ExaJobSearch
from app.core.job_discovery.location import location_matches
from app.core.job_discovery.sources.base import matches_query
from app.models.job import Job
from app.models.resume import Resume
from app.observability.metrics import job_searches_total, jobs_found_total
from app.schemas.job import (
    JobAnalysisResponse,
    JobListingResponse,
    JobListResponse,
    JobSearchRequest,
)

logger = structlog.get_logger(__name__)

#: Ceiling on rows read when a filter has to be evaluated in Python. Well above any
#: realistic personal job cache, and low enough that a runaway account cannot turn a
#: single list call into an unbounded table scan.
MAX_STORED_SCAN = 2000


def _job_identity(job: Job) -> str:
    """Stable, non-empty ``platform_job_id`` for a scraped listing.

    Browser-scraped listings often arrive with a blank id (the agent returned no ``id`` field);
    without a stable value distinct listings collide on the ``(user, platform, platform_job_id)``
    unique constraint AND collapse during dedup. Derive one from the URL (hashed, so it fits the
    column and is stable) when the id is blank.
    """
    pid = (job.platform_job_id or "").strip()
    if pid:
        return pid
    url = (job.url or "").strip()
    if url:
        return "url:" + hashlib.sha1(url.encode()).hexdigest()[:16]
    return ""


async def search_jobs(
    db: AsyncSession,
    request: JobSearchRequest,
    user_id: str,
) -> JobListResponse:
    """Search for jobs across configured platforms.

    Iterates over requested platforms, calls each platform's ``search``
    method, converts results to ``Job`` model instances, and persists
    them to the database. Partial failures are logged and skipped so
    that results from healthy platforms are still returned.

    Args:
        db: Async database session.
        request: Job search parameters.

    Returns:
        Paginated list of matching job listings.
    """
    logger.info(
        "job_search_requested",
        query=request.query,
        location=request.location,
        platforms=request.platforms,
        limit=request.limit,
    )

    # `is None` rather than a truthiness check: an explicit empty list is a valid request
    # meaning "search nothing", and `or` would have turned it into "search everything".
    platforms_to_search = (
        list(SUPPORTED_PLATFORMS) if request.platforms is None else request.platforms
    )

    if not platforms_to_search:
        logger.warning("job_search.no_platforms_available")
        return JobListResponse(
            items=[],
            total=0,
            page=1,
            page_size=request.limit,
            has_next=False,
        )

    all_jobs: list[Job] = []

    # Pre-fetch the user's existing jobs keyed by (platform, id) so dedup happens in memory. The
    # previous per-listing SELECT ran under autoflush, so distinct listings sharing an empty/dup
    # platform_job_id collapsed onto one row (silent data loss) — this also removes that N+1.
    existing_by_key: dict[tuple[str, str], Job] = {
        (j.platform, j.platform_job_id): j
        for j in (
            await db.execute(select(Job).where(Job.user_id == user_id))
        ).scalars().all()
    }
    seen: set[tuple[str, str]] = set()

    def _register(job: Job) -> None:
        """Add a new job or fold it onto an already-known one; never append a duplicate."""
        ident = _job_identity(job)
        if not ident:  # no id and no url — can't key it; keep as-is (degenerate data)
            db.add(job)
            all_jobs.append(job)
            return
        # Persist the derived id so distinct blank-id listings don't collide on the unique index.
        job.platform_job_id = ident
        key = (job.platform, ident)
        if key in seen:
            return
        seen.add(key)
        existing = existing_by_key.get(key)
        if existing is not None:
            all_jobs.append(existing)
        else:
            db.add(job)
            existing_by_key[key] = job
            all_jobs.append(job)

    for platform_name in platforms_to_search:
        if not platform_registry.has(platform_name):
            logger.warning(
                "job_search.platform_not_registered",
                platform=platform_name,
            )
            continue

        try:
            platform = platform_registry.create(platform_name)
            listings: list[JobListing] = await platform.search(
                query=request.query,
                location=request.location,
                filters=request.filters or None,
            )
            logger.info(
                "job_search.platform_results",
                platform=platform_name,
                count=len(listings),
            )
            job_searches_total.labels(platform=platform_name).inc()
            jobs_found_total.labels(platform=platform_name).inc(len(listings))
        except Exception as exc:
            logger.error(
                "job_search.platform_search_failed",
                platform=platform_name,
                error=str(exc),
            )
            continue

        for listing in listings:
            try:
                _register(_listing_to_job(listing, user_id))
            except Exception as exc:
                logger.warning(
                    "job_search.listing_conversion_failed",
                    platform=platform_name,
                    listing_id=listing.platform_job_id,
                    error=str(exc),
                )
                continue

    # ------------------------------------------------------------------
    # Exa AI semantic search (supplementary, non-blocking)
    # ------------------------------------------------------------------
    try:
        settings = get_settings()
        exa_key = settings.exa_api_key.get_secret_value()
        exa = ExaJobSearch(api_key=exa_key)
        if exa.available:
            exa_listings = await exa.search_jobs(
                query=request.query,
                location=request.location,
                num_results=min(request.limit, 10),
            )
            for listing in exa_listings:
                try:
                    _register(_listing_to_job(listing, user_id))
                except Exception:
                    continue
            logger.info("job_search.exa_results", count=len(exa_listings))
            job_searches_total.labels(platform="exa").inc()
            jobs_found_total.labels(platform="exa").inc(len(exa_listings))
    except Exception as exc:
        logger.debug("job_search.exa_skipped", reason=str(exc))

    if all_jobs:
        try:
            await db.commit()
            for job in all_jobs:
                await db.refresh(job)
        except Exception as exc:
            logger.error("job_search.commit_failed", error=str(exc))
            await db.rollback()
            all_jobs = []

    # Apply limit
    limited = all_jobs[: request.limit]
    items = [JobListingResponse.model_validate(j) for j in limited]

    return JobListResponse(
        items=items,
        total=len(all_jobs),
        page=1,
        page_size=request.limit,
        has_next=len(all_jobs) > request.limit,
    )


def _listing_to_job(listing: JobListing, user_id: str) -> Job:
    """Convert a platform ``JobListing`` to a ``Job`` database model.

    Args:
        listing: Normalized job listing from a platform scraper.

    Returns:
        A new unsaved ``Job`` model instance.
    """
    salary_range: str | None = None
    if listing.salary_min is not None and listing.salary_max is not None:
        salary_range = (
            f"{listing.salary_currency} "
            f"{listing.salary_min:,.0f} - {listing.salary_max:,.0f}"
        )
    elif listing.salary_min is not None:
        salary_range = f"{listing.salary_currency} {listing.salary_min:,.0f}+"
    elif listing.salary_max is not None:
        salary_range = f"Up to {listing.salary_currency} {listing.salary_max:,.0f}"

    skills_dict: dict[str, Any] | None = None
    if listing.skills_required or listing.skills_preferred:
        skills_dict = {
            "required": listing.skills_required,
            "preferred": listing.skills_preferred,
        }

    return Job(
        user_id=user_id,
        platform=listing.platform,
        platform_job_id=listing.platform_job_id,
        title=listing.title,
        company=listing.company,
        location=listing.location,
        url=listing.url,
        description=listing.description,
        salary_range=salary_range,
        job_type=listing.job_type or None,
        remote=listing.remote,
        skills_required=skills_dict,
        status="new",
    )


async def list_jobs(
    db: AsyncSession,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    status: str | None = None,
    *,
    location: str | None = None,
    query: str | None = None,
) -> JobListResponse:
    """List stored jobs, optionally filtered by location and title.

    ``location`` and ``query`` used to be absent entirely, and that was the whole of the
    "London filter does nothing" bug: the page fetched every cached job and filtered the
    result on ATS, salary and seniority — never on where the job was. A search for London
    therefore showed every job the account had ever discovered, from any search.

    Both filters are applied **server-side**, for two reasons that matter beyond tidiness:
    pagination is computed from the filtered count, so page 2 of a London search is London
    jobs rather than whatever survived a client-side pass over page 1; and the totals the UI
    reports ("38 roles") are then the real number of matches.

    Location is matched in Python rather than SQL. The rule is not a substring test — a
    London filter has to accept "EC4N 6EU" and "Canary Wharf" while rejecting "United
    Kingdom" — and expressing that as SQL would mean either a LIKE that is wrong or an
    extension SQLite does not have. See :mod:`app.core.job_discovery.location`.

    Args:
        db: Async database session.
        page: Page number (1-indexed).
        page_size: Items per page.
        status: Optional status filter.
        location: Optional place filter, e.g. ``"London"`` or ``"London, UK"``.
        query: Optional title filter, scored the same way discovery scores titles.

    Returns:
        Paginated job list response whose ``total`` counts matches, not stored rows.
    """
    page_size = min(page_size, MAX_PAGE_SIZE)
    offset = (page - 1) * page_size

    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)

    wants_location = bool((location or "").strip())
    wants_query = bool((query or "").strip())

    if not (wants_location or wants_query):
        # Unfiltered: count in SQL and page in SQL, as before.
        count_stmt = select(func.count(Job.id))
        if status:
            count_stmt = count_stmt.where(Job.status == status)
        total = (await db.execute(count_stmt)).scalar() or 0
        rows = (
            await db.execute(
                stmt.order_by(Job.created_at.desc()).offset(offset).limit(page_size)
            )
        ).scalars().all()
        items = [JobListingResponse.model_validate(j) for j in rows]
        return JobListResponse(
            items=items, total=total, page=page, page_size=page_size,
            has_next=(page * page_size) < total,
        )

    # Filtered: the predicate is not expressible in SQL, so the candidate set is read and
    # filtered here. Bounded by MAX_STORED_SCAN so a large account cannot turn one list call
    # into an unbounded read.
    candidates = (
        await db.execute(stmt.order_by(Job.created_at.desc()).limit(MAX_STORED_SCAN))
    ).scalars().all()

    matched = [
        job
        for job in candidates
        if (not wants_location
            or location_matches(location or "", job.location or "", remote=bool(job.remote)))
        and (not wants_query
             or matches_query(query or "", job.title or "", _skills_text(job)))
    ]

    total = len(matched)
    items = [
        JobListingResponse.model_validate(j) for j in matched[offset : offset + page_size]
    ]
    return JobListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )


def _skills_text(job: Job) -> str:
    """The job's skill tags as one string, for title/tag relevance scoring."""
    skills = job.skills_required
    if isinstance(skills, dict):
        required = skills.get("required")
        if isinstance(required, list):
            return " ".join(str(s) for s in required)
        return " ".join(str(k) for k in skills)
    if isinstance(skills, list):
        return " ".join(str(s) for s in skills)
    return ""


async def get_job(db: AsyncSession, job_id: str) -> Job:
    """Get a single job by ID.

    Args:
        db: Async database session.
        job_id: UUID of the job.

    Returns:
        The Job model instance.

    Raises:
        RecordNotFoundError: If job does not exist.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise RecordNotFoundError("Job", job_id)
    return job


async def delete_job(db: AsyncSession, job_id: str) -> None:
    """Delete a job by ID.

    Args:
        db: Async database session.
        job_id: UUID of the job to delete.

    Raises:
        RecordNotFoundError: If job does not exist.
    """
    job = await get_job(db, job_id)
    await db.delete(job)
    await db.commit()
    logger.info("job_deleted", job_id=job_id)


async def analyze_job(
    db: AsyncSession,
    job_id: str,
    resume_id: str | None = None,
) -> JobAnalysisResponse:
    """Analyze job-candidate match using ATS scoring.

    If a resume_id is provided, loads the resume and runs multi-factor
    ATS scoring (skills, keywords, experience, education). Falls back to
    placeholder scores when spaCy is not available or no resume is given.

    Args:
        db: Async database session.
        job_id: UUID of the job to analyze.
        resume_id: Optional UUID of the resume to score against.

    Returns:
        Job analysis with match scores and suggestions.

    Raises:
        RecordNotFoundError: If job does not exist.
    """
    job = await get_job(db, job_id)
    logger.info("job_analysis_requested", job_id=job_id, title=job.title)

    # If no resume provided, return placeholder scores
    if not resume_id:
        return JobAnalysisResponse(
            job_id=job.id,
            match_score=0.0,
            skill_match=0.0,
            keyword_match=0.0,
            missing_skills=[],
            suggestions=[
                "Provide a resume_id to get accurate ATS scoring.",
            ],
        )

    # Load resume
    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id),
    )
    resume = resume_result.scalar_one_or_none()
    if resume is None:
        raise RecordNotFoundError("Resume", resume_id)

    resume_text = resume.content_text or ""
    if not resume_text:
        return JobAnalysisResponse(
            job_id=job.id,
            match_score=0.0,
            skill_match=0.0,
            keyword_match=0.0,
            missing_skills=[],
            suggestions=[
                "Resume has no extracted text. Re-upload for analysis.",
            ],
        )

    # Attempt ATS scoring with spaCy
    try:
        import spacy

        nlp = spacy.load("en_core_web_sm")
        from app.core.ats.experience_analyzer import ExperienceAnalyzer
        from app.core.ats.keyword_analyzer import KeywordAnalyzer
        from app.core.ats.scorer import ResumeScorer
        from app.core.ats.skill_matcher import SkillMatcher

        skill_matcher = SkillMatcher(nlp)
        keyword_analyzer = KeywordAnalyzer(nlp)
        experience_analyzer = ExperienceAnalyzer(nlp)

        scorer = ResumeScorer(
            skill_matcher=skill_matcher,
            keyword_analyzer=keyword_analyzer,
            experience_analyzer=experience_analyzer,
        )

        job_description = job.description or ""
        job_metadata: dict[str, Any] = {}
        if job.skills_required and isinstance(job.skills_required, dict):
            job_metadata["required_skills"] = job.skills_required.get(
                "required", job.skills_required.get("skills", []),
            )
            job_metadata["preferred_skills"] = job.skills_required.get(
                "preferred", [],
            )

        # Extract skills from resume text for candidate profile
        detected_skills = list(skill_matcher.extract_skills(resume_text))
        candidate_profile: dict[str, Any] = {
            "skills": detected_skills,
            "experience": [],
            "education": [],
        }

        details = scorer.score_resume(
            resume_text=resume_text,
            job_description=job_description,
            candidate_profile=candidate_profile,
            job_metadata=job_metadata,
        )

        return JobAnalysisResponse(
            job_id=job.id,
            match_score=details.overall_score,
            skill_match=details.skill_score,
            keyword_match=details.keyword_score,
            missing_skills=details.missing_required_skills,
            suggestions=details.improvement_suggestions,
        )

    except (ImportError, OSError) as exc:
        logger.warning(
            "job_analysis.spacy_unavailable",
            error=str(exc),
        )
        return JobAnalysisResponse(
            job_id=job.id,
            match_score=0.0,
            skill_match=0.0,
            keyword_match=0.0,
            missing_skills=[],
            suggestions=[
                "spaCy NLP model not available. Install with: "
                "python -m spacy download en_core_web_sm",
            ],
        )
