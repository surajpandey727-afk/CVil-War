"""Job listing API routes."""

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.config.constants import DEFAULT_PAGE_SIZE
from app.core.ratelimit import rate_limit
from app.schemas.company import CompanyProfile
from app.schemas.fit import FitAnalysis, FitRequest
from app.schemas.job import (
    JobAnalysisResponse,
    JobListingResponse,
    JobListResponse,
    JobSearchRequest,
)
from app.services import company as company_service
from app.services import fit as fit_service
from app.services import job_search as job_service
from app.services import resume as resume_service

logger = structlog.get_logger(__name__)
router = APIRouter()

# Job search fans out to browser automation / Exa — cap per-client rate.
_COSTLY = Depends(rate_limit(30, 60))


@router.post(
    "/search",
    response_model=JobListResponse,
    dependencies=[_COSTLY],
    summary="Search for jobs across platforms",
)
async def search_jobs(
    request: JobSearchRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> JobListResponse:
    """Launch a multi-platform job search for the current user."""
    return await job_service.search_jobs(db, request, user.id)


@router.get("/", response_model=JobListResponse, summary="List jobs with pagination")
async def list_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    status: str | None = Query(default=None),
    location: str | None = Query(
        default=None,
        description=(
            "Filter to a place, e.g. 'London'. Matched against the stored job location: "
            "boroughs and London postcodes count, 'United Kingdom' and 'Remote' do not."
        ),
    ),
    q: str | None = Query(default=None, description="Filter by job title relevance."),
    db: AsyncSession = Depends(get_tenant_db),
) -> JobListResponse:
    """List the current user's stored job listings.

    ``location`` and ``q`` are applied here rather than in the browser. Filtering client-side
    meant ``total`` counted every stored job and page 2 of a London search was not London —
    the filter existed only in the rendered list.
    """
    return await job_service.list_jobs(
        db, page, page_size, status, location=location, query=q
    )


@router.get("/{job_id}", response_model=JobListingResponse, summary="Get a single job")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> JobListingResponse:
    """Get one of the current user's job listings by ID. Returns 404 if not found."""
    job = await job_service.get_job(db, job_id)
    return JobListingResponse.model_validate(job)


@router.post(
    "/{job_id}/analyze", response_model=JobAnalysisResponse, summary="Analyze job-candidate match"
)
async def analyze_job(
    job_id: str,
    resume_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_tenant_db),
) -> JobAnalysisResponse:
    """Analyze how well the candidate matches a job listing."""
    return await job_service.analyze_job(db, job_id, resume_id=resume_id)


@router.post(
    "/{job_id}/fit",
    response_model=FitAnalysis,
    dependencies=[_COSTLY],
    summary="Assess one CV against this job",
)
async def analyse_fit(
    job_id: str,
    request: FitRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> FitAnalysis:
    """Job-first fit analysis: the job is the context, the CV is the variable.

    Returns per-category scores, every requirement with the CV text that evidences it, the
    gaps classified by how far off they are, and recommendations grounded in material the CV
    already contains. A stored analysis for this exact (job, CV) pair is reused unless
    ``refresh`` is set, so reopening a job costs nothing.

    Nothing here invents experience: quoted evidence is verified against the CV before it is
    reported, and a requirement the CV cannot support comes back as missing.
    """
    job = await job_service.get_job(db, job_id)
    resume = await resume_service.get_resume(db, request.resume_id)

    if not request.refresh:
        stored = await fit_service.load_stored(
            db, job_id=job_id, resume_id=request.resume_id
        )
        if stored is not None:
            return stored

    settings = await _user_settings(db, user.id)
    return await fit_service.analyse(
        db,
        user_id=user.id,
        job=job,
        resume=resume,
        target_location=settings[0],
        salary_expectation_k=settings[1],
    )


@router.get(
    "/{job_id}/fit",
    response_model=FitAnalysis | None,
    summary="The stored fit assessment for this job, if one exists",
)
async def stored_fit(
    job_id: str,
    resume_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_tenant_db),
) -> FitAnalysis | None:
    """Return a previous assessment without recomputing.

    When ``resume_id`` names a different CV than the stored analysis used, the analysis still
    comes back — with ``stale_reason`` set. Hiding it would lose information the operator
    already paid for; showing it unlabelled would be worse.
    """
    await job_service.get_job(db, job_id)
    return await fit_service.load_stored(db, job_id=job_id, resume_id=resume_id)


@router.get(
    "/{job_id}/company",
    response_model=CompanyProfile,
    summary="What is known about this employer",
)
async def company_profile(
    job_id: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> CompanyProfile:
    """Company profile assembled from stored data only.

    Under the zero-cost constraint there is no enrichment API, so most fields are genuinely
    unknowable and the response says which. What is real: the employer name, their official
    site where the source is a known career board, and the other roles of theirs already in
    your list.
    """
    job = await job_service.get_job(db, job_id)
    return await company_service.profile_for(db, job)


async def _user_settings(db: AsyncSession, user_id: str) -> tuple[str, int]:
    """The operator's target location and salary floor, for the categories that need them.

    Read from the automation policy rather than a second copy: the salary floor the fit
    analysis compares against must be the same number the apply gate enforces.
    """
    from app.services.policy import load_policy

    policy = await load_policy(db, user_id)
    return "", policy.min_salary_k


@router.delete("/{job_id}", status_code=204, summary="Delete a job")
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Delete one of the current user's job listings and its applications."""
    await job_service.delete_job(db, job_id)
