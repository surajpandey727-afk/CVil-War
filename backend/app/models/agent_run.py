"""One row per agent invocation — the audit trail and live-status source for Agent Ops.

Deliberately a thin, generic log rather than a per-agent table: every agent (Discovery,
Eligibility, Scoring, ...) writes the same shape, so the Agent Ops view and the
``GET /api/v1/agent-runs`` endpoint have one query to make regardless of which agent is
being inspected.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import AgentName, AgentRunStatus


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One invocation of one agent, with enough context to answer "what did it do, and to
    what" without reading logs."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_user_started", "user_id", "started_at"),)

    agent_name: Mapped[AgentName] = mapped_column(pg_enum(AgentName, "agent_name"), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        pg_enum(AgentRunStatus, "agent_run_status"), nullable=False, default=AgentRunStatus.RUNNING
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: One line each — this is a status feed, not a second copy of the trajectory/timeline.
    input_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    output_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What this run was about, e.g. "job" / "user" — free text, not a foreign key, since a
    #: Discovery run's subject is a user while a Scoring run's is a job.
    linked_entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    linked_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<AgentRun(agent={self.agent_name}, status={self.status}, id={self.id})>"
