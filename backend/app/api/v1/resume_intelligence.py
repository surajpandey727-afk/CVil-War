"""Resume Intelligence API routes.

The integration seam with the rest of CVil-War is intentionally just two endpoints:
``POST /tailor`` (takes a job_id — the "JOB" shape from the integration contract) and
``POST /tailor/{analysis_id}/commit`` (returns a ResumeVersionSummary — the "RESUME_REFERENCE"
shape). See services.resume_intelligence and services.resume_tailoring module docstrings.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.core.exceptions import RecordNotFoundError
from app.core.ratelimit import rate_limit
from app.models.application import Application
from app.models.resume_intelligence import ResumeBranch
from app.schemas.resume_intelligence import (
    ApplicationResumeVersionOut,
    CommitTailorRequest,
    CommitTailorResponse,
    CreateBranchRequest,
    MarketSignalsResponse,
    ResumeBranchDetail,
    ResumeBranchSummary,
    ResumeIntelligenceOverview,
    ResumeVersionDetail,
    RestoreVersionRequest,
    TailorRequest,
    TailorResponse,
    UpdateMasterRequest,
    VersionDiff,
)
from app.services import resume_intelligence as ri
from app.services import resume_tailoring as rt

router = APIRouter()

# Tailoring costs an LLM call; everything else here is plain DB CRUD.
_COSTLY = Depends(rate_limit(20, 60))


@router.get("/overview", response_model=ResumeIntelligenceOverview, summary="Dashboard summary")
async def get_overview(
    user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> ResumeIntelligenceOverview:
    return await ri.get_overview(db, user.id)


@router.get("/master", response_model=ResumeVersionDetail, summary="Get the master résumé")
async def get_master(
    user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> ResumeVersionDetail:
    version = await ri.get_or_create_master(db, user.id)
    return await ri.get_version(db, user.id, version.id)


@router.put("/master", response_model=ResumeVersionDetail, summary="Edit the master résumé")
async def update_master(
    data: UpdateMasterRequest, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> ResumeVersionDetail:
    version = await ri.update_master(db, user.id, data.content, data.commit_message)
    return await ri.get_version(db, user.id, version.id)


@router.get("/master/versions", response_model=list[ri.ResumeVersionDetail], summary="Master version history")
async def list_master_versions(
    user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> list:
    return await ri.list_versions(db, user.id, branch_id=None)


@router.get("/branches", response_model=list[ResumeBranchSummary], summary="List role branches")
async def list_branches(
    user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> list[ResumeBranchSummary]:
    return await ri.list_branches(db, user.id)


@router.post("/branches", response_model=ResumeBranchSummary, status_code=201, summary="Create a role branch")
async def create_branch(
    data: CreateBranchRequest, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> ResumeBranchSummary:
    return await ri.create_branch(db, user.id, data)


@router.get("/branches/{branch_id}", response_model=ResumeBranchDetail, summary="Role profile detail")
async def get_branch(
    branch_id: str, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> ResumeBranchDetail:
    return await ri.get_branch(db, user.id, branch_id)


@router.delete("/branches/{branch_id}", status_code=204, summary="Delete a role branch")
async def delete_branch(
    branch_id: str, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> None:
    await ri.delete_branch(db, user.id, branch_id)


@router.get("/branches/{branch_id}/versions", response_model=list[ri.ResumeVersionDetail], summary="Branch version history / change log")
async def list_branch_versions(
    branch_id: str, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> list:
    await ri.get_branch(db, user.id, branch_id)  # 404 + tenant check
    return await ri.list_versions(db, user.id, branch_id=branch_id)


@router.get("/branches/{branch_id}/market-signals", response_model=MarketSignalsResponse, summary="Aggregated market signals for a role")
async def get_market_signals(
    branch_id: str, user: CurrentUser, force: bool = False, db: AsyncSession = Depends(get_tenant_db),
) -> MarketSignalsResponse:
    branch = (
        await db.execute(
            select(ResumeBranch).where(ResumeBranch.id == branch_id, ResumeBranch.user_id == user.id)
        )
    ).scalar_one_or_none()
    if branch is None:
        raise RecordNotFoundError("ResumeBranch", branch_id)
    return await rt.compute_market_signals(db, user.id, branch, force=force)


@router.get("/versions/diff", response_model=VersionDiff, summary="Diff two versions")
async def diff_versions(
    from_id: str, to_id: str, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> VersionDiff:
    # Registered before /versions/{version_id}: FastAPI matches path routes in registration
    # order, and a static "/versions/diff" registered after the dynamic segment would be
    # swallowed by it (version_id="diff" -> a 404 "ResumeVersion 'diff' not found" instead of
    # ever reaching this handler). Confirmed live by a failing integration test.
    return await ri.diff_versions(db, user.id, from_id, to_id)


@router.get("/versions/{version_id}", response_model=ri.ResumeVersionDetail, summary="One version's full content and changes")
async def get_version(
    version_id: str, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
):
    return await ri.get_version(db, user.id, version_id)


@router.post("/versions/{version_id}/restore", response_model=ri.ResumeVersionSummary, summary="Restore an earlier version (creates a new version)")
async def restore_version(
    version_id: str, data: RestoreVersionRequest, user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
):
    return await ri.restore_version(db, user.id, version_id, data.commit_message)


@router.post("/tailor", response_model=TailorResponse, dependencies=[_COSTLY], summary="Analyse a job against a role branch and propose changes")
async def tailor(
    data: TailorRequest, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> TailorResponse:
    return await rt.tailor_job(db, user.id, data)


@router.post("/tailor/{analysis_id}/commit", response_model=CommitTailorResponse, summary="Commit accepted/edited changes as a new version")
async def commit_tailor(
    analysis_id: str, data: CommitTailorRequest, user: CurrentUser,
    db: AsyncSession = Depends(get_tenant_db),
) -> CommitTailorResponse:
    return await rt.commit_tailor(db, user.id, analysis_id, data)


@router.get(
    "/applications/{application_id}/resume-version",
    response_model=ApplicationResumeVersionOut,
    summary="Which résumé version an application actually used",
)
async def get_application_resume_version(
    application_id: str, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db),
) -> ApplicationResumeVersionOut:
    app = (
        await db.execute(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    ).scalar_one_or_none()
    if app is None:
        raise RecordNotFoundError("Application", application_id)
    version_label = None
    branch_role_name = None
    if app.resume_version_id:
        version = await ri.get_version_row(db, user.id, app.resume_version_id)
        version_label = version.version_label
        if version.branch_id:
            branch = await db.get(ResumeBranch, version.branch_id)
            branch_role_name = branch.role_name if branch else None
    return ApplicationResumeVersionOut(
        application_id=app.id, resume_version_id=app.resume_version_id,
        version_label=version_label, branch_role_name=branch_role_name,
    )
