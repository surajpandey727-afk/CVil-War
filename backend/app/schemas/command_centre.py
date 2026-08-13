"""Schemas for the command centre: action queue, summary, timeline."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ActionPriority,
    ApplicationEventType,
    ApplicationHealth,
    ApplicationStatus,
    NextAction,
)


class ActionItem(BaseModel):
    """One row of the action queue."""

    model_config = ConfigDict(from_attributes=True)

    application_id: str
    job_id: str
    title: str
    company: str
    action: NextAction
    priority: ActionPriority
    #: Plain-English justification, shown verbatim — the user must be able to sanity-check
    #: the ranking, or they stop trusting the queue.
    reason: str
    score: float
    due_at: datetime | None = None
    health: ApplicationHealth
    status: ApplicationStatus
    #: Which surface resolves this action, so a click lands on the exact thing to do
    #: rather than a page the user must navigate onward from.
    target: str
    application_url: str | None = None
    portal: str | None = None


class ActionQueueResponse(BaseModel):
    items: list[ActionItem] = Field(default_factory=list)
    total: int = 0
    by_priority: dict[str, int] = Field(default_factory=dict)


class CommandCentreSummary(BaseModel):
    """Everything the dashboard's top panels need, in one call."""

    total_applications: int = 0
    needs_attention: int = 0
    high_priority: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    #: Operational health, which is not the hiring status — an application can be at
    #: INTERVIEW and simultaneously BLOCKED on an expired session.
    by_health: dict[str, int] = Field(default_factory=dict)
    upcoming_interviews: int = 0
    pending_assessments: int = 0
    top_actions: list[ActionItem] = Field(default_factory=list)


class TimelineEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: ApplicationEventType
    occurred_at: datetime
    summary: str
    detail: str | None = None
    actor: str
    payload: dict | None = None


class ApplicationTimelineResponse(BaseModel):
    application_id: str
    entries: list[TimelineEntry] = Field(default_factory=list)
    total: int = 0
    current_action: NextAction = NextAction.NONE
    current_reason: str = ""
