"""Schemas for the Agent Ops surface: live agent state + run history."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AgentName, AgentRunStatus


class AgentRunItem(BaseModel):
    """One row of agent activity — a single agent invocation, start to finish."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_name: AgentName
    status: AgentRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error: str | None = None
    linked_entity_type: str | None = None
    linked_entity_id: str | None = None


class AgentNodeState(BaseModel):
    """The live-graph view's per-agent node: its most recent run, whatever that is."""

    agent_name: AgentName
    status: AgentRunStatus | None = None
    last_run: AgentRunItem | None = None


class AgentRunListResponse(BaseModel):
    """Filtered run history plus the current node state for every named agent."""

    items: list[AgentRunItem]
    total: int
    nodes: list[AgentNodeState]
