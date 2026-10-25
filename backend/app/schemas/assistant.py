"""Assistant chat, confirmation and AI Agents roster contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_HISTORY = 20
MAX_MESSAGE_CHARS = 8000


class ChatMessage(BaseModel):
    """Text-only history: the client never sends tool blocks or thinking back."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_HISTORY)


class ToolCallSummary(BaseModel):
    name: str
    input_summary: str = ""
    ok: bool
    result_summary: str = ""


class PendingAction(BaseModel):
    token: str
    summary: str


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    pending: list[PendingAction] = Field(default_factory=list)
    model: str


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=4096)


class ConfirmResponse(BaseModel):
    ok: bool
    message: str


class PrepareRequest(BaseModel):
    """Propose an agent action from the AI Agents page (same token flow as the chat)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["run_discovery_now"]


class PrepareResponse(BaseModel):
    ok: bool
    pending: PendingAction | None = None
    message: str = ""


AgentStatus = Literal["idle", "running", "needs_attention", "off"]


class AgentLastRun(BaseModel):
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    summary: str | None = None
    error: str | None = None


class AgentCount(BaseModel):
    label: str
    value: int


class AgentAction(BaseModel):
    label: str
    #: "link": navigate to ``to``; "confirm": prepare ``action`` and show a confirm card.
    kind: Literal["link", "confirm"]
    to: str | None = None
    action: str | None = None


class AgentCard(BaseModel):
    key: str
    name: str
    description: str
    status: AgentStatus
    status_text: str
    last_run: AgentLastRun | None = None
    #: False when this agent has no run log yet (Résumé, Assistant), so "never ran" is not
    #: claimed for something that simply isn't recorded.
    tracks_runs: bool = True
    counts: list[AgentCount] = Field(default_factory=list)
    actions: list[AgentAction] = Field(default_factory=list)
    section: AgentAction


class AgentRosterResponse(BaseModel):
    agents: list[AgentCard]
    assistant_available: bool
