"""Pydantic schemas for Resume Intelligence.

The structured content model (``ResumeContent`` and its sections) is the master/branch
résumé's actual stored shape — chosen so a single achievement bullet can be changed without
touching the rest of the document (see the product requirement this was built against:
"Achievements should be individually addressable").
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured résumé content — what a ResumeVersion.content JSON blob contains.
# ---------------------------------------------------------------------------


class Achievement(BaseModel):
    id: str = ""
    text: str = ""
    technologies: list[str] = Field(default_factory=list)
    #: What backs this claim — a project name, a stored record. Free text; see
    #: ResumeChange.evidence for why this stays lightweight rather than a graph table.
    evidence: str = ""


class ExperienceEntry(BaseModel):
    id: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    achievements: list[Achievement] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    evidence: str = ""
    link: str = ""


class EducationEntry(BaseModel):
    degree: str = ""
    institution: str = ""
    graduation_year: str = ""
    gpa: str | None = None


class ResumeHeader(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""


class ResumeContent(BaseModel):
    header: ResumeHeader = Field(default_factory=ResumeHeader)
    summary: str = ""
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    additional: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Versions / branches / changes
# ---------------------------------------------------------------------------


class ResumeChangeOut(BaseModel):
    id: str
    change_type: str
    section: str
    before_text: str | None
    after_text: str | None
    reason: str
    source_job_id: str | None
    evidence: str | None
    status: str
    created_at: datetime


class ResumeVersionSummary(BaseModel):
    id: str
    branch_id: str | None
    version_label: str
    sequence: int
    source: str
    commit_message: str
    content_hash: str
    created_at: datetime


class ResumeVersionDetail(ResumeVersionSummary):
    content: ResumeContent
    changes: list[ResumeChangeOut] = Field(default_factory=list)


class ResumeBranchSummary(BaseModel):
    id: str
    role_name: str
    role_family: str
    description: str
    current_version: ResumeVersionSummary | None
    market_signals_computed_at: datetime | None


class ResumeBranchDetail(ResumeBranchSummary):
    current_content: ResumeContent | None
    market_signals: dict[str, dict] | None


class ResumeIntelligenceOverview(BaseModel):
    master_version: ResumeVersionSummary | None
    branches: list[ResumeBranchSummary]
    recent_changes_count: int


class CreateBranchRequest(BaseModel):
    role_name: str
    role_family: str = "product"
    description: str = ""


class UpdateMasterRequest(BaseModel):
    content: ResumeContent
    commit_message: str = "Updated master résumé"


class RestoreVersionRequest(BaseModel):
    commit_message: str = ""


class VersionDiffEntry(BaseModel):
    section: str
    path: str
    before: str | None = None
    after: str | None = None


class VersionDiff(BaseModel):
    from_version_id: str
    to_version_id: str
    added: list[VersionDiffEntry] = Field(default_factory=list)
    removed: list[VersionDiffEntry] = Field(default_factory=list)
    modified: list[VersionDiffEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Market signals
# ---------------------------------------------------------------------------


class SkillSignal(BaseModel):
    frequency: float
    matched_jobs: int
    total_jobs: int


class MarketSignalsResponse(BaseModel):
    branch_id: str
    signals: dict[str, SkillSignal]
    matched_jobs: int
    total_jobs_scanned: int
    computed_at: datetime


# ---------------------------------------------------------------------------
# Job tailoring
# ---------------------------------------------------------------------------


class TailorRequest(BaseModel):
    job_id: str
    #: Auto-selects the best-matching branch by title overlap when omitted.
    branch_id: str | None = None


class TitleAnalysisOut(BaseModel):
    current_title: str
    target_title: str
    relationship: str
    shared_experience: list[str] = Field(default_factory=list)
    positioning_opportunity: str = ""


class ProposedChangeOut(BaseModel):
    id: str
    change_type: str
    section: str
    before_text: str | None
    after_text: str | None
    reason: str
    evidence: str | None


class TailorResponse(BaseModel):
    analysis_id: str
    branch_id: str
    branch_role_name: str
    base_version_id: str
    matched: dict[str, str]
    partial: dict[str, str]
    missing: dict[str, str]
    ats_alignment_pct: float | None
    role_fit_notes: str
    positioning_notes: str
    title_analysis: TitleAnalysisOut | None
    proposed_changes: list[ProposedChangeOut]


class ChangeDecision(BaseModel):
    change_id: str
    decision: str  # "accept" | "reject" | "edit"
    edited_after_text: str | None = None


class CommitTailorRequest(BaseModel):
    decisions: list[ChangeDecision]
    commit_message: str = ""


class CommitTailorResponse(BaseModel):
    version: ResumeVersionSummary
    accepted_count: int
    rejected_count: int
    ats_alignment_before: float | None
    ats_alignment_after: float | None


class TailorLLMChange(BaseModel):
    """One LLM-proposed edit — the structured-output shape enforced on the tailoring call."""

    change_type: str = "modified"
    section: str = ""
    before_text: str = ""
    after_text: str = ""
    reason: str = ""
    evidence: str = ""


class TailorLLMTitleAnalysis(BaseModel):
    current_title: str = ""
    target_title: str = ""
    relationship: str = "related"
    shared_experience: list[str] = Field(default_factory=list)
    positioning_opportunity: str = ""


class TailorLLMOutput(BaseModel):
    """The LLM's full structured response for one job-tailoring analysis."""

    contextually_satisfied: dict[str, str] = Field(default_factory=dict)
    still_missing: list[str] = Field(default_factory=list)
    ats_alignment_pct: float = 0.0
    role_fit_notes: str = ""
    positioning_notes: str = ""
    title_analysis: TailorLLMTitleAnalysis = Field(default_factory=TailorLLMTitleAnalysis)
    proposed_changes: list[TailorLLMChange] = Field(default_factory=list)


class ApplicationResumeVersionOut(BaseModel):
    application_id: str
    resume_version_id: str | None
    version_label: str | None
    branch_role_name: str | None
