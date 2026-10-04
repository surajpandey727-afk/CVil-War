"""Resume Intelligence: a factual master résumé, role-specific branches derived from it, and
git-style version control with a fully explainable change log.

Deliberately four tables, not six or ten (see the product brief this was built against):
a "master résumé" has no table of its own — it is simply the lineage of
:class:`ResumeVersion` rows with ``branch_id IS NULL`` for a user, so branching the master
into a role and branching a role into nothing further both use the exact same mechanism. A
"role profile" is the same row as a "résumé branch" — they are 1:1 by construction, so one
table (:class:`ResumeBranch`) carries both the git-branch concept and the market-facing
profile fields (market signals, description) rather than splitting them for no operational
reason.

Every table inherits :class:`TenantMixin`, so the existing ``do_orm_execute`` tenant filter
(``app.db.tenant``) scopes every SELECT to the owning user automatically — the same guarantee
every other table in this product already has, not a new security mechanism.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import (
    ResumeChangeStatus,
    ResumeChangeType,
    ResumeVersionSource,
    RoleFamily,
)


class ResumeBranch(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """A role-specific branch derived from the master résumé — also the role's market profile.

    ``market_signals``/``market_signals_computed_at`` are a cache, not live data: recomputing
    skill frequency across every matching job on every page view would mean an LLM-free but
    still real DB scan on every request (see performance requirement — recalculate only when
    explicitly refreshed or stale, never per-view).
    """

    __tablename__ = "resume_branches"
    __table_args__ = (Index("ix_resume_branch_user", "user_id"),)

    role_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_family: Mapped[RoleFamily] = mapped_column(
        pg_enum(RoleFamily, "role_family"), nullable=False, default=RoleFamily.PRODUCT
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: {"skill": {"frequency": 0.62, "matched_jobs": 14, "total_jobs": 23}, ...} — every number
    #: here must trace back to a real count over real Job rows; never a fabricated statistic.
    market_signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    market_signals_computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    versions: Mapped[list[ResumeVersion]] = relationship(
        back_populates="branch", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ResumeBranch(id={self.id}, role_name='{self.role_name}')>"


class ResumeVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One immutable, git-style commit of résumé content.

    ``branch_id IS NULL`` means this version belongs to the MASTER résumé, not a role branch
    — the one lineage every branch's first version is seeded from. ``sequence`` is a simple
    per-lineage incrementing counter (1, 2, 3, ...) used only to render "v1.3"-style labels
    without parsing ``version_label`` back out; the label itself is the display value and is
    never parsed programmatically.
    """

    __tablename__ = "resume_versions"
    __table_args__ = (
        Index("ix_resume_version_user_branch", "user_id", "branch_id"),
        Index("ix_resume_version_parent", "parent_version_id"),
    )

    branch_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("resume_branches.id", ondelete="CASCADE"), nullable=True
    )
    parent_version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("resume_versions.id", ondelete="SET NULL"), nullable=True
    )
    #: Display label only ("MAIN v1.0", "AI-PM v2.3") — see docstring; never parsed back.
    version_label: Mapped[str] = mapped_column(String(60), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The full structured résumé content at this version — header/summary/experience (with
    #: per-achievement evidence)/projects/education/skills/certifications/additional. See
    #: services.resume_intelligence for the exact shape; kept as JSON rather than normalised
    #: tables because a résumé's shape is read/written as one coherent document far more often
    #: than any single field is queried in isolation.
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    #: SHA-256 of the canonicalised content — cheap equality/identity check (e.g. "does this
    #: application's resume_version_id still match what's live") without diffing JSON blobs.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[ResumeVersionSource] = mapped_column(
        pg_enum(ResumeVersionSource, "resume_version_source"),
        nullable=False, default=ResumeVersionSource.INITIAL,
    )
    commit_message: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    branch: Mapped[ResumeBranch | None] = relationship(back_populates="versions")
    changes: Mapped[list[ResumeChange]] = relationship(
        back_populates="version", cascade="all, delete-orphan",
        order_by="ResumeChange.created_at",
    )

    def __repr__(self) -> str:
        return f"<ResumeVersion(id={self.id}, label='{self.version_label}')>"


class ResumeChange(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One explainable, individually-reviewable edit belonging to a version's commit.

    A single ``ResumeVersion`` commit typically bundles several of these (e.g. "reframed
    summary" + "added LLM experience" + "reordered skills") — the change log renders per
    version, each change expandable to its own before/why/source/evidence, per the product's
    core traceability requirement. ``status`` starts PROPOSED for AI-suggested changes (never
    applied to content until accepted) and is ACCEPTED immediately for direct user edits.
    """

    __tablename__ = "resume_changes"
    __table_args__ = (Index("ix_resume_change_version", "version_id"),)

    #: Null while PROPOSED (a tailoring suggestion has no version yet — it IS the candidate
    #: for one) and set once the operator commits it into a new ResumeVersion. analysis_id
    #: is what a proposed-but-not-yet-committed change is actually attached to.
    version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=True
    )
    analysis_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("job_resume_analyses.id", ondelete="CASCADE"), nullable=True
    )
    change_type: Mapped[ResumeChangeType] = mapped_column(
        pg_enum(ResumeChangeType, "resume_change_type"), nullable=False
    )
    #: Which content section this touched — "summary" | "experience" | "skills" | ... — a
    #: free label, not an enum: new sections must not require a migration to describe.
    section: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    before_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_job_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    #: What backs this change — a project name, a stored achievement, "market analysis". Free
    #: text: the evidence graph this product wants is lightweight pointers, not a new table.
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ResumeChangeStatus] = mapped_column(
        pg_enum(ResumeChangeStatus, "resume_change_status"),
        nullable=False, default=ResumeChangeStatus.ACCEPTED,
    )

    version: Mapped[ResumeVersion | None] = relationship(back_populates="changes")

    def __repr__(self) -> str:
        return f"<ResumeChange(id={self.id}, type='{self.change_type}')>"


class JobResumeAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    """One job's tailoring analysis against a résumé branch — the record behind "Tailor résumé".

    ``proposed_version_id`` stays null until the operator reviews and commits the proposed
    changes (see services.resume_tailoring); the analysis itself is never mutated afterward,
    so it remains an honest record of what was actually proposed and why.
    """

    __tablename__ = "job_resume_analyses"
    __table_args__ = (Index("ix_job_resume_analysis_user_job", "user_id", "job_id"),)

    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("resume_branches.id", ondelete="CASCADE"), nullable=False
    )
    base_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False
    )
    #: Skill name -> short evidence/context string, one bucket each. Every entry here must
    #: trace to something real (a skills-list match, LLM-reasoned contextual coverage, or an
    #: explicit absence) — never a filler list.
    matched: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    partial: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    missing: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    unsupported: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: 0-1. "Resume-job alignment" — never framed as an interview probability (see ATS
    #: analysis requirement: explainable breakdown, not a single black-box confidence score).
    ats_alignment_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    role_fit_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    positioning_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: {"current_title","target_title","relationship","shared_experience":[...],"positioning_opportunity"}
    title_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    proposed_version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("resume_versions.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<JobResumeAnalysis(id={self.id}, job_id={self.job_id})>"
