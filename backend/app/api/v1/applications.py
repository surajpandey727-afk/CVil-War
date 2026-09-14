"""Application tracking API routes."""

import httpx
import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_redis, get_tenant_db
from app.config.constants import DEFAULT_PAGE_SIZE
from app.core.automation.intervention import resolve_intervention
from app.core.exceptions import RecordNotFoundError
from app.core.ratelimit import rate_limit
from app.db.arq import get_arq_pool
from app.models.enums import ApplicationEventType, ApplicationStatus
from app.models.job import Job
from app.schemas.application import (
    ApplicationBatchCreate,
    ApplicationBulkApprove,
    ApplicationCreate,
    ApplicationIntervention,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationStatusUpdate,
    CoverLetterResponse,
)
from app.schemas.communications import LogRecruiterContactRequest, LogRecruiterContactResponse
from app.schemas.evidence import ApplicationEvidence
from app.services import apollo as apollo_service
from app.services import application as app_service
from app.services import cover_letter as cover_letter_service
from app.services import dispatch
from app.services.evidence import build_evidence
from app.services.readiness import apply_readiness
from app.services.timeline import record_event

logger = structlog.get_logger(__name__)
router = APIRouter()

# Apply dispatch + cover-letter generation trigger LLM/browser work — cap per-client rate.
_COSTLY = Depends(rate_limit(30, 60))


@router.post(
    "/", response_model=ApplicationResponse, status_code=201, dependencies=[_COSTLY],
    summary="Create an application",
)
async def create_application(
    data: ApplicationCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
    pool: ArqRedis | None = Depends(get_arq_pool),
) -> ApplicationResponse:
    """Create a single job application and dispatch it according to apply_mode."""
    app = await app_service.create_application(db, data, user.id)
    await dispatch.dispatch_for_mode(db, pool, app)
    return app_service.application_to_response(app)


@router.post(
    "/batch",
    response_model=list[ApplicationResponse],
    status_code=201,
    dependencies=[_COSTLY],
    summary="Batch create applications",
)
async def batch_create(
    data: ApplicationBatchCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
    pool: ArqRedis | None = Depends(get_arq_pool),
) -> list[ApplicationResponse]:
    """Create multiple job applications at once, each dispatched by apply_mode."""
    apps = await app_service.create_batch(db, data, user.id)
    for app in apps:
        await dispatch.dispatch_for_mode(db, pool, app)
    return [app_service.application_to_response(a) for a in apps]


@router.get("/", response_model=ApplicationListResponse, summary="List applications")
async def list_applications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationListResponse:
    """List the current user's applications with pagination and optional status filter."""
    return await app_service.list_applications(db, page, page_size, status)


@router.post(
    "/bulk-approve",
    response_model=dict,
    summary="Approve and enqueue a set of staged (batch) applications",
)
async def bulk_approve(
    data: ApplicationBulkApprove,
    db: AsyncSession = Depends(get_tenant_db),
    pool: ArqRedis | None = Depends(get_arq_pool),
) -> dict:
    """Approve a set of the current user's staged applications and enqueue them together."""
    count = await dispatch.bulk_approve(db, pool, data.application_ids)
    return {"approved": count}


@router.get("/{app_id}", response_model=ApplicationResponse, summary="Get a single application")
async def get_application(
    app_id: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationResponse:
    """Get one of the current user's applications by ID. Returns 404 if not found."""
    app = await app_service.get_application(db, app_id)
    return app_service.application_to_response(app)


@router.get(
    "/{app_id}/evidence",
    response_model=ApplicationEvidence,
    summary="Everything needed to prove what happened to this application",
)
async def get_application_evidence(
    app_id: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationEvidence:
    """Job, submission, documents, account, run log and failure detail for one application.

    Assembled from records the system already writes; sections that were never captured come
    back with ``recorded: false`` so the UI reports "Not recorded" rather than rendering a
    convincing blank. No credential is read on this path — the account section carries a
    masked label and a connection state, nothing more.
    """
    app = await app_service.get_application(db, app_id)
    return await build_evidence(db, app)


@router.put(
    "/{app_id}/approve",
    response_model=ApplicationResponse,
    summary="Approve a pending application",
)
async def approve_application(
    app_id: str,
    db: AsyncSession = Depends(get_tenant_db),
    pool: ArqRedis | None = Depends(get_arq_pool),
) -> ApplicationResponse:
    """Approve a pending application and enqueue it for automated submission."""
    app = await app_service.approve_application(db, app_id)
    await dispatch.enqueue_apply(pool, app.id)
    return app_service.application_to_response(app)


@router.post(
    "/{app_id}/cover-letter",
    response_model=CoverLetterResponse,
    dependencies=[_COSTLY],
    summary="Generate a cover letter for an application",
)
async def generate_cover_letter(
    app_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> CoverLetterResponse:
    """Generate (LLM) and store a cover letter for the application's job + resume."""
    app = await cover_letter_service.generate_cover_letter(db, app_id, user.id)
    return CoverLetterResponse(application_id=app.id, cover_letter_path=app.cover_letter_path)


@router.post(
    "/{app_id}/intervention",
    response_model=dict,
    summary="Resolve a pending CAPTCHA/2FA intervention",
)
async def resolve_application_intervention(
    app_id: str,
    data: ApplicationIntervention,
    db: AsyncSession = Depends(get_tenant_db),
    redis: Redis | None = Depends(get_redis),
) -> dict:
    """Deliver the user's response to a worker waiting on a CAPTCHA/2FA challenge."""
    await app_service.get_application(db, app_id)  # 404 + tenant-ownership check
    if redis is None:
        return {"resolved": False, "detail": "intervention channel unavailable"}
    await resolve_intervention(redis, app_id, data.response)
    return {"resolved": True}


@router.post(
    "/{app_id}/resolve-blocker",
    response_model=dict,
    dependencies=[_COSTLY],
    summary="Resume an application paused for CAPTCHA/verification",
)
async def resolve_application_blocker(
    app_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
    pool: ArqRedis | None = Depends(get_arq_pool),
) -> dict:
    """Re-queue a verification-blocked application, headed, once the operator has cleared
    the challenge themselves in the browser window that opened for it.

    Distinct from ``/intervention`` (which relays a typed 2FA/OTP code to a worker still
    blocked mid-run): a CAPTCHA cannot be solved by typing a code into this dashboard, so
    the original run already stopped and paused (``workers.tasks._mark_needs_verification``).
    This starts a fresh, headed attempt rather than resuming the finished one.
    """
    app = await app_service.get_application(db, app_id)  # 404 + tenant-ownership check
    app.status = ApplicationStatus.QUEUED
    app.resume_state = {**(app.resume_state or {}), "force_headed": True}
    await db.commit()
    job_id = await dispatch.enqueue_apply(pool, app.id)
    return {"queued": job_id is not None}


@router.post(
    "/{app_id}/log-recruiter-contact",
    response_model=LogRecruiterContactResponse,
    dependencies=[_COSTLY],
    summary="Log a recruiter contact to Apollo and this application's timeline",
)
async def log_recruiter_contact(
    app_id: str,
    data: LogRecruiterContactRequest,
    db: AsyncSession = Depends(get_tenant_db),
) -> LogRecruiterContactResponse:
    """Record that the operator reached out to a recruiter for this application.

    Creates (or upserts) the contact in Apollo, and writes RECRUITER_CONTACTED +
    APOLLO_CONTACT_LOGGED on the application's own timeline — the one durable record of
    outreach, whether or not Apollo itself is ever opened again to check it.
    """
    app = await app_service.get_application(db, app_id)  # 404 + tenant-ownership check
    job = await db.get(Job, app.job_id)
    try:
        result = await apollo_service.log_contact(
            email=data.email, first_name=data.first_name, last_name=data.last_name,
            organization_name=job.company if job else "", title=data.title,
        )
    except apollo_service.ApolloNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Apollo rejected the request: {exc.response.status_code}"
        ) from exc
    summary = f"Contacted {data.first_name} {data.last_name}".strip() or f"Contacted {data.email}"
    await record_event(
        db, app, ApplicationEventType.RECRUITER_CONTACTED, summary,
        payload={"email": data.email, "apollo_contact_id": result.contact_id},
    )
    await record_event(
        db, app, ApplicationEventType.APOLLO_CONTACT_LOGGED,
        "Logged to Apollo" + (" (existing contact updated)" if result.matched_existing else ""),
        payload={"apollo_contact_id": result.contact_id}, recompute=False,
    )
    await db.commit()
    return LogRecruiterContactResponse(
        contact_id=result.contact_id, matched_existing=result.matched_existing
    )


@router.put(
    "/{app_id}/status",
    response_model=ApplicationResponse,
    summary="Update application status",
)
async def update_status(
    app_id: str,
    update: ApplicationStatusUpdate,
    db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationResponse:
    """Update an application's status and optional notes."""
    app = await app_service.update_status(db, app_id, update)
    return app_service.application_to_response(app)


@router.get(
    "/readiness/{job_id}",
    summary="Whether the agent can apply to this job, and what is missing if not",
)
async def get_apply_readiness(
    job_id: str,
    user: CurrentUser,
    resume_id: str | None = None,
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, object]:
    """Check the apply prerequisites before the operator commits to a run.

    The worker already refuses to apply without a platform session, a CV and a model. Asking
    it there means the operator finds out from a failed application; asking it here means the
    screen can offer "Connect LinkedIn" while there is still something useful to do about it.

    Every blocker carries the action that clears it, so this can never produce a dead end.

    Explicitly scoped by ``user_id`` — ``job_id`` is attacker-reachable path input, and
    ``Session.get()`` does NOT go through the ORM tenant filter (it is a column/identity-map
    load, which the filter deliberately skips), so a plain ``db.get()`` here would let one
    operator read another's job.
    """
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    job = result.scalar_one_or_none()
    if job is None:
        raise RecordNotFoundError("Job not found")

    blockers = await apply_readiness(db, user.id, job, resume_id=resume_id)
    return {
        "job_id": job_id,
        "platform": job.platform,
        "ready": not blockers,
        # Applying by hand stays possible unless the listing has no link at all, so a blocked
        # agent run never means a blocked application.
        "manual_possible": all(b.manual_possible for b in blockers),
        "blockers": [
            {
                "code": b.code, "message": b.message, "action": b.action,
                "platform": b.platform,
            }
            for b in blockers
        ],
    }
