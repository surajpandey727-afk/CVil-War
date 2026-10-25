"""Résumé checker contract: one résumé against one job, or against the Skill Radar role set.

All scores are 0-1 (the API convention — multiply by 100 to display).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

EvidenceStatus = Literal["supported", "add_only_if_true"]
SectionKey = Literal["summary", "experience", "skills", "formatting"]


class ResumeCheckRequest(BaseModel):
    resume_id: str
    #: Check against this stored job's posting text...
    job_id: str | None = None
    #: ...or against the merged demand of these Skill Radar roles. Exactly one is required.
    role_titles: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _one_target(self) -> ResumeCheckRequest:
        if bool(self.job_id) == bool(self.role_titles):
            raise ValueError("Give exactly one target: job_id, or a non-empty role_titles list.")
        return self


class CheckTarget(BaseModel):
    kind: Literal["job", "roles"]
    job_id: str | None = None
    title: str
    company: str | None = None
    role_titles: list[str] = Field(default_factory=list)


class ScoreComponent(BaseModel):
    key: str
    label: str
    #: Share of the overall score (all weights sum to 1).
    weight: float
    score: float
    detail: str


class FitScore(BaseModel):
    overall: float
    band: Literal["strong", "decent", "gap"]
    components: list[ScoreComponent]
    #: Human-readable formula, e.g. "0.45 x must-have + 0.20 x nice-to-have + ...".
    formula: str


class Evidence(BaseModel):
    #: Verbatim line from the résumé (trimmed), never paraphrased.
    quote: str
    section: str


class MatchedSkill(BaseModel):
    key: str
    label: str
    category: str
    must_have: bool
    evidence: list[Evidence]


class MissingSkill(BaseModel):
    key: str
    label: str
    category: str
    must_have: bool
    #: How many of the scanned UK-eligible jobs mention this skill.
    uk_demand: int
    #: uk_demand / uk_jobs_scanned (0 when nothing was scanned).
    uk_demand_share: float


class AtsKeywords(BaseModel):
    coverage: float
    total: int
    found: list[str]
    missing: list[str]


class SectionReview(BaseModel):
    key: SectionKey
    label: str
    status: Literal["good", "needs_work", "missing"]
    score: float
    findings: list[str]


class Suggestion(BaseModel):
    section: SectionKey
    kind: Literal["rewrite", "add"]
    #: The résumé line being rewritten (verbatim); absent for "add" suggestions.
    original: str | None = None
    suggested: str
    reason: str
    #: "add_only_if_true" whenever the suggestion contains anything the résumé does not
    #: already evidence — a skill, a number, a named tool or organisation.
    evidence_status: EvidenceStatus
    source: Literal["rules", "llm"] = "rules"


class CorpusInfo(BaseModel):
    uk_jobs_scanned: int


class ResumeCheckResponse(BaseModel):
    resume_id: str
    resume_name: str
    target: CheckTarget
    score: FitScore
    matched_skills: list[MatchedSkill]
    #: Must-haves first, then by UK demand (most-asked first).
    missing_skills: list[MissingSkill]
    ats_keywords: AtsKeywords
    sections: list[SectionReview]
    suggestions: list[Suggestion]
    corpus: CorpusInfo


class SectionNote(BaseModel):
    section: SectionKey
    note: str


class ResumeReviewResponse(BaseModel):
    """The Claude narrative layer on top of the deterministic check."""

    available: bool
    #: Why it is unavailable (no key, provider error, invalid JSON) — shown to the user.
    detail: str | None = None
    model: str | None = None
    summary: str | None = None
    section_notes: list[SectionNote] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    #: LLM suggestions dropped by validation (quote not in the résumé, unknown section, ...).
    rejected_count: int = 0
