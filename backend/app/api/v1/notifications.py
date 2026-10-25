"""In-app notifications: the bell's feed, its unread badge, and marking things read."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_tenant_db
from app.services import notifications as service

router = APIRouter()


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    severity: str
    title: str
    body: str | None
    link: str | None
    created_at: datetime
    read_at: datetime | None
    emailed_at: datetime | None


class NotificationFeed(BaseModel):
    items: list[NotificationOut]
    unread: int


class MarkedRead(BaseModel):
    updated: int


@router.get("/", response_model=NotificationFeed, summary="Notification feed")
async def feed(
    unread_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_db),
) -> NotificationFeed:
    """Newest first, with the unread count so one request draws both the list and the badge."""
    rows = await service.list_for_user(db, unread_only=unread_only, limit=limit)
    return NotificationFeed(
        items=[NotificationOut.model_validate(r) for r in rows],
        unread=await service.unread_count(db),
    )


@router.get("/unread-count", response_model=MarkedRead, summary="Unread notification count")
async def unread(db: AsyncSession = Depends(get_tenant_db)) -> MarkedRead:
    """Cheap poll for the badge (``updated`` carries the count)."""
    return MarkedRead(updated=await service.unread_count(db))


@router.post("/read-all", response_model=MarkedRead, summary="Mark every notification read")
async def read_all(user: CurrentUser, db: AsyncSession = Depends(get_tenant_db)) -> MarkedRead:
    return MarkedRead(updated=await service.mark_read(db, user.id))


@router.post("/{notification_id}/read", response_model=MarkedRead, summary="Mark one read")
async def read_one(
    notification_id: str, user: CurrentUser, db: AsyncSession = Depends(get_tenant_db)
) -> MarkedRead:
    return MarkedRead(updated=await service.mark_read(db, user.id, notification_id))
