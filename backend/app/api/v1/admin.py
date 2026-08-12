"""Admin/health routes (superuser-only): surfaces harness-detected system issues."""

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.harness import SystemIssue
from app.schemas.admin import SystemIssueResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get(
    "/system-issues",
    response_model=list[SystemIssueResponse],
    summary="List harness-detected system issues",
)
async def list_system_issues(
    status: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[SystemIssue]:
    """Return recent SystemIssue rows (global; SystemIssue is not tenant-scoped)."""
    query = select(SystemIssue)
    if status:
        query = query.where(SystemIssue.status == status)
    query = query.order_by(SystemIssue.detected_at.desc()).limit(min(limit, 500))
    return list((await db.execute(query)).scalars().all())
