"""Self-evolving harness models: run trajectories, verdicts, diagnoses, skills, issues."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import FailureClass, RunVerdictResult, SkillStatus


class RunTrajectory(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One recorded apply run: the agent's steps + token/cost/timing summary."""

    __tablename__ = "run_trajectories"
    __table_args__ = (Index("ix_run_traj_user_created", "user_id", "created_at"),)

    application_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    screenshots: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    agent_self_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    # IDs of the domain skills injected into this run's prompt — the verdict feeds back to
    # score them (the self-evolving feedback loop).
    skills_used: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)


class RunVerdict(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """LLM-as-judge verdict on a run (independent of the agent's self-report)."""

    __tablename__ = "run_verdicts"

    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("run_trajectories.id", ondelete="CASCADE"), index=True
    )
    verdict: Mapped[RunVerdictResult] = mapped_column(
        pg_enum(RunVerdictResult, "run_verdict"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    judged_model: Mapped[str | None] = mapped_column(String(100), nullable=True)


class RunDiagnosis(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """Classified failure + root cause + suggested remediation for a non-success run."""

    __tablename__ = "run_diagnoses"

    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("run_trajectories.id", ondelete="CASCADE"), index=True
    )
    failure_class: Mapped[FailureClass] = mapped_column(
        pg_enum(FailureClass, "failure_class"), nullable=False
    )
    root_cause: Mapped[str] = mapped_column(Text, nullable=False, default="")
    signals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    suggested_action: Mapped[str | None] = mapped_column(String(200), nullable=True)


class DomainSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Distilled, shared site knowledge (institutional memory). Not tenant-scoped — it is
    curated cross-user knowledge, PII-gated before storage, scored, and versioned."""

    __tablename__ = "domain_skills"
    __table_args__ = (
        Index("ix_domain_skill_domain_status", "domain", "status"),
        UniqueConstraint("domain", "version", name="uq_domain_skill_version"),
    )

    domain: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[SkillStatus] = mapped_column(
        pg_enum(SkillStatus, "skill_status"), nullable=False, default=SkillStatus.ACTIVE
    )
    pii_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True)


class SkillFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A scored +/- signal (with a written reason) attached to a skill."""

    __tablename__ = "skill_feedback"

    skill_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("domain_skills.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A workflow/system anomaly detected by the harness (may be global or per-user)."""

    __tablename__ = "system_issues"
    __table_args__ = (Index("ix_system_issue_status_detected", "status", "detected_at"),)

    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    signals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
