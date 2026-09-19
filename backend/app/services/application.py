"""Application management service.

Handles creating, listing, approving, and updating job applications.
"""

import contextlib
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError as DBIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.exceptions import RecordNotFoundError
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.resume import Resume
from app.schemas.application import (
    ApplicationBatchCreate,
    ApplicationCreate,
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationStatusUpdate,
)

logger = structlog.get_logger(__name__)


def application_to_response(app: Application) -> ApplicationResponse:
    """Serialize an Application, hydrating the job and résumé display fields.

    The denormalized display fields are only filled when the relationship is already loaded
    (list/detail eager-load both); callers that pass an object without it loaded — e.g. a
    freshly created row — get ``None``, and never trigger a lazy load in the async context.

    The résumé name matters as much as the job title: an application that shows only a
    ``resume_id`` cannot answer "which CV did they actually get", which is the whole point of
    keeping the reference.
    """
    item = ApplicationResponse.model_validate(app)
    unloaded = sa_inspect(app).unloaded
    if "job" not in unloaded and app.job is not None:
        item.job_title = app.job.title
        item.company = app.job.company
    if "resume" not in unloaded and app.resume is not None:
        item.resume_name = app.resume.name
        # str(), not .value: the column holds a StrEnum but a row written in this session and
        # not yet refreshed still carries the plain string it was assigned.
        item.resume_type = str(app.resume.type)
        item.resume_ats_score = app.resume.ats_score
        item.resume_archived = app.resume.archived_at is not None
    item.has_cover_letter = bool(app.cover_letter_path)
    return item

# States that DON'T block a fresh application for the same (user, job) — mirrors the
# partial-unique ``uq_app_active_job`` index.
_TERMINAL_STATES = (
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
    ApplicationStatus.FAILED,
)


async def _assert_owned(db: AsyncSession, model: Any, record_id: str) -> None:
    """Confirm a referenced record exists for the current tenant before linking to it.

    The ``do_orm_execute`` filter is SELECT-only, so it never validates FK targets on
    INSERT — without this a client could create an Application referencing another
    tenant's job_id/resume_id. The scoped SELECT returns None for a foreign id.
    """
    found = (
        await db.execute(select(model.id).where(model.id == record_id))
    ).scalar_one_or_none()
    if found is None:
        raise RecordNotFoundError(f"{model.__name__} '{record_id}' not found")


def apply_job_provenance(application: Application, job: Job | None) -> None:
    """Copy the job's platform and application URL onto the application at creation.

    Both columns existed and neither was ever written, so every application recorded which
    job it came from but not which board it lived on or where a human could open it. That is
    the difference between "you applied" and "you applied *there*, and here is the page".

    Snapshotted rather than read through the relationship on demand: a job row can be
    re-scraped and its URL changed, and the application is supposed to say where the
    submission actually went, not where the posting later moved to.
    """
    if job is None:
        return
    application.portal = application.portal or job.platform or None
    application.application_url = (
        application.application_url or job.application_url or job.url or None
    )


async def create_application(
    db: AsyncSession,
    data: ApplicationCreate,
    user_id: str,
) -> Application:
    """Create a single job application.

    Args:
        db: Async database session.
        data: Application creation data.

    Returns:
        The newly created Application.
    """
    await _assert_owned(db, Job, data.job_id)
    if data.resume_id:
        await _assert_owned(db, Resume, data.resume_id)

    application = Application(
        user_id=user_id,
        job_id=data.job_id,
        resume_id=data.resume_id,
        apply_mode=data.apply_mode,
        status=ApplicationStatus.QUEUED,
    )
    apply_job_provenance(application, await db.get(Job, data.job_id))
    # Attempt the insert inside a SAVEPOINT so a unique-constraint violation rolls back
    # ONLY this insert (not the whole session) — the caller then continues to commit.
    try:
        async with db.begin_nested():
            db.add(application)
            await db.flush()
    except DBIntegrityError:
        # An active application for this (user, job) already exists — return it (idempotent
        # create), so a double-submit/retry can't create a duplicate auto-apply.
        existing = (
            await db.execute(
                select(Application).where(
                    Application.job_id == data.job_id,
                    Application.status.notin_(_TERMINAL_STATES),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("application_create_idempotent", app_id=existing.id, job_id=data.job_id)
            return existing
        raise
    await db.commit()
    await db.refresh(application)
    logger.info("application_created", app_id=application.id, job_id=data.job_id)
    return application


async def create_batch(
    db: AsyncSession,
    data: ApplicationBatchCreate,
    user_id: str,
) -> list[Application]:
    """Create multiple applications at once.

    Args:
        db: Async database session.
        data: Batch creation data containing multiple job IDs.

    Returns:
        List of newly created Applications.
    """
    if data.resume_id:
        await _assert_owned(db, Resume, data.resume_id)
    requested = set(data.job_ids)
    owned = set(
        (await db.execute(select(Job.id).where(Job.id.in_(requested)))).scalars().all()
    )
    missing = requested - owned
    if missing:
        raise RecordNotFoundError(f"Jobs not found: {sorted(missing)}")

    # Skip jobs that already have an active application (dedup, mirrors uq_app_active_job).
    existing_active = set(
        (
            await db.execute(
                select(Application.job_id).where(
                    Application.job_id.in_(requested),
                    Application.status.notin_(_TERMINAL_STATES),
                )
            )
        ).scalars().all()
    )

    applications: list[Application] = []
    for job_id in data.job_ids:
        if job_id in existing_active:
            continue
        app = Application(
            user_id=user_id,
            job_id=job_id,
            resume_id=data.resume_id,
            apply_mode=data.apply_mode,
            status=ApplicationStatus.QUEUED,
        )
        apply_job_provenance(app, await db.get(Job, job_id))
        db.add(app)
        applications.append(app)

    await db.commit()
    for app in applications:
        await db.refresh(app)

    logger.info("batch_applications_created", count=len(applications))
    return applications


async def list_applications(
    db: AsyncSession,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    status: str | None = None,
) -> ApplicationListResponse:
    """List applications with pagination and optional status filter.

    Args:
        db: Async database session.
        page: Page number (1-indexed).
        page_size: Items per page.
        status: Optional status filter.

    Returns:
        Paginated application list response.
    """
    page_size = min(page_size, MAX_PAGE_SIZE)
    offset = (page - 1) * page_size

    query = select(Application).options(
        selectinload(Application.job), selectinload(Application.resume)
    )
    count_query = select(func.count(Application.id))

    if status:
        query = query.where(Application.status == status)
        count_query = count_query.where(Application.status == status)

    query = query.order_by(Application.created_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    apps = list(result.scalars().all())

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    items = [application_to_response(app) for app in apps]

    return ApplicationListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )


async def get_application(db: AsyncSession, app_id: str) -> Application:
    """Get a single application by ID.

    Args:
        db: Async database session.
        app_id: UUID of the application.

    Returns:
        The Application model instance.

    Raises:
        RecordNotFoundError: If application does not exist.
    """
    result = await db.execute(
        select(Application)
        .where(Application.id == app_id)
        .options(selectinload(Application.job), selectinload(Application.resume)),
    )
    app = result.scalar_one_or_none()
    if app is None:
        raise RecordNotFoundError("Application", app_id)
    return app


async def approve_application(db: AsyncSession, app_id: str) -> Application:
    """Approve a pending application for submission.

    Args:
        db: Async database session.
        app_id: UUID of the application to approve.

    Returns:
        The updated Application.

    Raises:
        RecordNotFoundError: If application does not exist.
    """
    app = await get_application(db, app_id)
    if app.status not in (ApplicationStatus.PENDING_REVIEW, ApplicationStatus.QUEUED):
        raise ValueError(
            f"Cannot approve application in '{app.status}' state. "
            "Only pending_review or queued applications can be approved."
        )
    app.status = ApplicationStatus.APPROVED
    await db.commit()
    await db.refresh(app)
    logger.info("application_approved", app_id=app_id)
    return app


async def update_status(
    db: AsyncSession,
    app_id: str,
    update: ApplicationStatusUpdate,
) -> Application:
    """Update an application's status and optional notes.

    Args:
        db: Async database session.
        app_id: UUID of the application.
        update: Status update payload.

    Returns:
        The updated Application.

    Raises:
        RecordNotFoundError: If application does not exist.
    """
    app = await get_application(db, app_id)
    was_applied = app.status == ApplicationStatus.APPLIED
    app.status = update.status
    if update.notes is not None:
        app.notes = update.notes
    if update.resume_id is not None:
        # Tenant-scoped: Resume, like Application, is auto-filtered to the current user by
        # the ORM's do_orm_execute hook, so a resume_id belonging to another tenant simply
        # doesn't match here rather than being silently attached.
        resume = (
            await db.execute(select(Resume).where(Resume.id == update.resume_id))
        ).scalar_one_or_none()
        if resume is None:
            raise RecordNotFoundError("Resume not found")
        app.resume_id = update.resume_id
    if update.status == ApplicationStatus.APPLIED:
        app.applied_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(app)
    logger.info("application_status_updated", app_id=app_id, status=update.status)

    # Only the transition INTO applied fires a notification — not every subsequent edit to an
    # already-applied row (e.g. adding notes later). Best-effort, mirrors workers.tasks._apply.
    if update.status == ApplicationStatus.APPLIED and not was_applied:
        with contextlib.suppress(Exception):
            from app.services.gmail_send import send_application_confirmation

            job = await db.get(Job, app.job_id)
            await send_application_confirmation(
                db, app.user_id,
                job_title=(job.title if job else "this role"),
                company=(job.company if job else "the employer"),
                platform=(job.platform if job else "manual"),
            )
    return app
