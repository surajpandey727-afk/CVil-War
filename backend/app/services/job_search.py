"""Job search and management service.

Handles job CRUD operations, search orchestration across platform
scrapers, and ATS-based job analysis.
"""

import asyncio
import hashlib
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.config.settings import get_settings
from app.core.automation.platforms import platform_registry
from app.core.automation.platforms.base import JobListing
from app.core.exceptions import RecordNotFoundError
from app.core.job_discovery.exa_search import ExaJobSearch
from app.core.job_discovery.location import location_matches
from app.core.job_discovery.source_registry import usable_keys
from app.core.job_discovery.sources.base import matches_query
from app.core.sponsorship.classify import classify as classify_sponsor
from app.models.enums import JobStatus, SponsorConfidence
from app.models.job import Job
from app.models.resume import Resume
from app.observability.metrics import job_searches_total, jobs_found_total
from app.schemas.job import (
    JobAnalysisResponse,
    JobListingResponse,
    JobListResponse,
    JobSearchRequest,
)
from app.services.policy import load_policy, parse_salary_k

logger = structlog.get_logger(__name__)

#: Ceiling on rows read when a filter has to be evaluated in Python. Well above any
#: realistic personal job cache, and low enough that a runaway account cannot turn a
#: single list call into an unbounded table scan.
MAX_STORED_SCAN = 2000

#: Concurrent source fetches in one search. The default fan-out now legitimately covers
#: 60+ sources (see the default-platforms fix); unbounded concurrency would open that many
#: simultaneous outbound connections per search, which is its own way to look like an
#: attack to some of these upstreams. Bounded, not sequential, is the actual fix — measured
#: live: a full default search went from well over a minute to a few seconds.
_MAX_CONCURRENT_SOURCE_FETCHES = 10

#: Wall-clock ceiling on the whole fetch phase, not any one source. A few slow/rate-limited
#: sources retrying with backoff (see sources.base) can each occupy a concurrency slot for
#: a long time; bounding the total keeps an interactive search answerable even when several
#: of ~65 default sources are currently struggling, at the cost of dropping whichever
#: haven't answered yet — same trade-off already made per-source, just at the search level.
_SEARCH_FETCH_DEADLINE_S = 20.0


class _UnregisteredPlatformError(Exception):
    """Sentinel: no adapter is registered under this key. Not a fetch failure."""


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
    #
    # The default fan-out is resolved through the source registry's live health, not a
    # hand-maintained constant — a static list is exactly how Reed and Adzuna ended up
    # correctly implemented, correctly credentialed, and never once queried by a default
    # search: they were simply never added to it. `usable_keys()` derives "usable" from
    # each source's actual registration/credential/known-broken state, so a newly wired
    # source is included the moment it is registered, and a source that goes dark (a
    # revoked key, a scraper that breaks) drops out without another hand-edit here.
    platforms_to_search = usable_keys() if request.platforms is None else request.platforms

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

    # Fetching is concurrent (bounded); registering results into `db`/`all_jobs` stays
    # strictly sequential afterward, unchanged from before. Measured real-world cause: the
    # default fan-out used to be ~9 sources, so a sequential loop was never a problem — it
    # now legitimately covers 60+ (see the default-platforms fix), and one HTTP round trip
    # per source in series turned a sub-second search into well over a minute. `AsyncSession`
    # is not safe for concurrent I/O across tasks, so nothing here touches `db` until every
    # fetch has already resolved on the main task.
    fetch_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SOURCE_FETCHES)

    async def _fetch_one(platform_name: str) -> tuple[str, list[JobListing], Exception | None]:
        if not platform_registry.has(platform_name):
            return platform_name, [], _UnregisteredPlatformError()
        async with fetch_semaphore:
            try:
                platform = platform_registry.create(platform_name)
                listings = await platform.search(
                    query=request.query,
                    location=request.location,
                    filters=request.filters or None,
                )
                return platform_name, listings, None
            except Exception as exc:
                return platform_name, [], exc

    # An overall deadline on top of bounded concurrency: measured live, a full ~65-source
    # default fan-out still took over a minute even with the semaphore above, because a
    # handful of slow/rate-limited scraped sources (now retried with backoff — see the
    # source-base retry fix) can each hold a concurrency slot for a long time. A source
    # that hasn't answered by the deadline degrades exactly like any other per-source
    # failure — no results this round — rather than making the whole search wait on it.
    tasks = [asyncio.ensure_future(_fetch_one(name)) for name in platforms_to_search]
    done, pending = await asyncio.wait(tasks, timeout=_SEARCH_FETCH_DEADLINE_S)
    for task in pending:
        task.cancel()
    if pending:
        logger.warning(
            "job_search.fetch_deadline_exceeded",
            timed_out=len(pending),
            completed=len(done),
        )
    fetch_results = [t.result() for t in done]

    for platform_name, listings, error in fetch_results:
        if isinstance(error, _UnregisteredPlatformError):
            logger.warning("job_search.platform_not_registered", platform=platform_name)
            continue
        if error is not None:
            logger.error(
                "job_search.platform_search_failed", platform=platform_name, error=str(error),
            )
            continue

        logger.info(
            "job_search.platform_results", platform=platform_name, count=len(listings),
        )
        job_searches_total.labels(platform=platform_name).inc()
        jobs_found_total.labels(platform=platform_name).inc(len(listings))

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
    #
    # Deliberately silent no-op vs. loud failure: not configuring EXA_API_KEY is a normal,
    # expected operator choice (one line, INFO, once per search) — but an exception from an
    # Exa call that IS configured is a real defect, not a market signal, and must not be
    # indistinguishable from "no matches" (see the platform directive: never silently
    # return an empty result for a source that should have worked).
    # ------------------------------------------------------------------
    settings = get_settings()
    exa_key = settings.exa_api_key.get_secret_value()
    exa = ExaJobSearch(api_key=exa_key)
    if not exa.available:
        logger.info(
            "job_search.exa_not_configured",
            reason="no EXA_API_KEY" if not exa_key else "exa-py not installed",
        )
    else:
        try:
            exa_listings = await exa.search_jobs(
                query=request.query,
                location=request.location,
                num_results=min(request.limit, 10),
            )
            for listing in exa_listings:
                try:
                    _register(_listing_to_job(listing, user_id))
                except Exception as exc:
                    logger.warning(
                        "job_search.exa_listing_conversion_failed", error=str(exc),
                    )
                    continue
            logger.info("job_search.exa_results", count=len(exa_listings))
            job_searches_total.labels(platform="exa").inc()
            jobs_found_total.labels(platform="exa").inc(len(exa_listings))
        except Exception as exc:
            # Configured but failed: a real, unexpected problem — loud, not a debug crumb.
            logger.warning("job_search.exa_failed", error=str(exc)[:300])

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
    # Serialised before the dedup pass on purpose: that pass commits, which expires every
    # ORM instance, and validating an expired Job then triggers a lazy load with no greenlet
    # to run it in. Pydantic models hold plain values and are unaffected.
    items = [JobListingResponse.model_validate(j) for j in limited]

    # Link listings that describe one vacancy. Best-effort: a dedup failure must not lose the
    # jobs the search just found.
    if all_jobs:
        try:
            await assign_canonical_ids(db, user_id)
        except Exception as exc:
            logger.warning("job_search.dedup_failed", error=str(exc))
            await db.rollback()

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

    # Stamped for every listing regardless of source, so the boost in list_jobs() (and any
    # future consumer) never has to ask which board a job came from.
    sponsor_confidence, sponsor_evidence = classify_sponsor(
        listing.company, listing.description
    )

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
        sponsor_confidence=sponsor_confidence,
        sponsor_evidence=sponsor_evidence,
    )


#: Sponsor-confirmed roles rank above equal-fit non-sponsor roles — never a hard filter, and
#: never an override of a real signal the user asked for (location, title, salary). Lower is
#: better, so a plain sort on this value puts CONFIRMED_REGISTER first.
_SPONSOR_RANK: dict[SponsorConfidence, int] = {
    SponsorConfidence.CONFIRMED_REGISTER: 0,
    SponsorConfidence.KEYWORD_DETECTED: 1,
    SponsorConfidence.LIKELY: 2,
    SponsorConfidence.UNKNOWN: 3,
    SponsorConfidence.NOT_SPONSOR: 4,
}


def _passes_hard_criteria(
    job: Job, *, min_salary_k: int, excluded_employment_types: frozenset[str]
) -> bool:
    """Salary floor and employment-type exclusion — real hard filters, unlike the sponsor
    boost. A posting with no published salary band is kept (see policy §5.2's own reasoning:
    most UK postings omit one, and filtering on absence would discard most of the market)."""
    if min_salary_k:
        band = parse_salary_k(job.salary_range)
        if band is not None and band < min_salary_k:
            return False
    return not (
        excluded_employment_types
        and (job.job_type or "").strip().casefold() in excluded_employment_types
    )


async def list_jobs(
    db: AsyncSession,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    status: str | None = None,
    *,
    location: str | None = None,
    query: str | None = None,
    user_id: str | None = None,
) -> JobListResponse:
    """List stored jobs, optionally filtered by location, title, and the operator's criteria.

    ``location`` and ``query`` used to be absent entirely, and that was the whole of the
    "London filter does nothing" bug: the page fetched every cached job and filtered the
    result on ATS, salary and seniority — never on where the job was. A search for London
    therefore showed every job the account had ever discovered, from any search.

    All of it is applied **server-side**, for two reasons that matter beyond tidiness:
    pagination is computed from the filtered count, so page 2 of a London search is London
    jobs rather than whatever survived a client-side pass over page 1; and the totals the UI
    reports ("38 roles") are then the real number of matches.

    Location is matched in Python rather than SQL. The rule is not a substring test — a
    London filter has to accept "EC4N 6EU" and "Canary Wharf" while rejecting "United
    Kingdom" — and expressing that as SQL would mean either a LIKE that is wrong or an
    extension SQLite does not have. See :mod:`app.core.job_discovery.location`.

    ``user_id`` opts into the operator's own criteria: their salary floor and excluded
    employment types (both real, hard filters — a below-floor or excluded-type job is not
    returned at all) and a sponsor-confidence ranking boost (never a hard filter — a
    sponsor-confirmed role sorts above an equal non-sponsor one, but nothing is hidden for
    lacking sponsorship evidence). ``None`` preserves the old, criteria-free behaviour, which
    existing callers with no notion of "whose policy" rely on.

    Args:
        db: Async database session.
        page: Page number (1-indexed).
        page_size: Items per page.
        status: Optional status filter.
        location: Optional place filter, e.g. ``"London"`` or ``"London, UK"``.
        query: Optional title filter, scored the same way discovery scores titles.
        user_id: Whose salary floor, employment-type exclusions, and sponsor ranking to apply.

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

    min_salary_k = 0
    excluded_employment_types: frozenset[str] = frozenset()
    if user_id is not None:
        policy = await load_policy(db, user_id)
        min_salary_k = policy.min_salary_k
        excluded_employment_types = frozenset(
            t.strip().casefold() for t in policy.exclude_employment_types if t.strip()
        )

    if not (wants_location or wants_query or user_id is not None):
        # Unfiltered and no operator context: count in SQL and page in SQL, as before.
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
        and _passes_hard_criteria(
            job, min_salary_k=min_salary_k, excluded_employment_types=excluded_employment_types
        )
    ]

    if user_id is not None:
        # Stable sort: candidates already arrived created_at-desc from the query above, so
        # jobs within the same sponsor band keep that recency order — only the band changes.
        matched.sort(key=lambda j: _SPONSOR_RANK.get(j.sponsor_confidence, 3))

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


async def update_job_status(db: AsyncSession, job_id: str, status: JobStatus) -> Job:
    """Save, hide, or otherwise change a job's lifecycle status.

    There was previously no way to do this at all — a job only ever moved to APPLIED as a
    side effect of creating an application. "Save this for later" and "hide this, I'm not
    interested" had no endpoint to call.

    Args:
        db: Async database session.
        job_id: UUID of the job.
        status: The new status.

    Returns:
        The updated Job.

    Raises:
        RecordNotFoundError: If job does not exist.
    """
    job = await get_job(db, job_id)
    job.status = status
    await db.commit()
    await db.refresh(job)
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


async def assign_canonical_ids(db: AsyncSession, user_id: str) -> int:
    """Group this user's jobs by vacancy and stamp each group with a shared canonical id.

    ``canonical_job_id`` has existed since the Job OS migration and nothing populated it, so
    the same vacancy discovered on Reed, LinkedIn and the employer's own board was three
    unrelated rows — three list entries, three fit analyses, and three applications to one
    employer for one role.

    The oldest row in each group is the canonical one: it is the listing the operator saw
    first, and keeping the choice stable means a later re-scrape does not reshuffle which id
    everything points at. A group of one still gets stamped, so "has been deduplicated" and
    "has not been examined" stay distinguishable.

    Returns the number of rows updated.
    """
    from app.core.job_discovery.dedup import JobIdentity
    from app.core.job_discovery.dedup import group as group_identities

    rows = list(
        (
            await db.execute(
                select(Job).where(Job.user_id == user_id).order_by(Job.created_at)
            )
        ).scalars().all()
    )
    if not rows:
        return 0

    identities = [
        JobIdentity(
            source=row.platform or "",
            source_id=row.platform_job_id or "",
            company=row.company or "",
            title=row.title or "",
            location=row.location or "",
            url=row.url or "",
            application_url=row.application_url or "",
        )
        for row in rows
    ]

    updated = 0
    duplicates = 0
    for cluster in group_identities(identities):
        # Rows are ordered by created_at, so the lowest index is the earliest discovery.
        canonical = rows[min(cluster)]
        if len(cluster) > 1:
            duplicates += len(cluster) - 1
        for index in cluster:
            row = rows[index]
            if row.canonical_job_id != canonical.id:
                row.canonical_job_id = canonical.id
                updated += 1

    if updated:
        await db.commit()
    logger.info(
        "job_search.canonical_ids_assigned",
        rows=len(rows),
        updated=updated,
        duplicates_linked=duplicates,
    )
    return updated
