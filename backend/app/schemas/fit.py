"""Wire format for the job-vs-CV fit analysis.

Three rules are encoded in these shapes rather than left to the implementation's good
intentions, because every one of them has an obvious failure mode:

**A category is only reported when the job actually said something about it.** A "salary fit"
of 90% against a posting with no published band is a number invented out of nothing, and it
looks exactly like a measured one. Hence :class:`FitCategory` is only ever emitted for
dimensions the posting supplies, and the reason why a dimension is absent is stated.

**Every claimed match points at where in the CV it came from.** ``evidence`` is not a
paraphrase — it is the text found, and ``source`` says which part of the CV it was found in.
A match with no evidence is not a match, it is an assertion.

**A gap says what kind of gap it is.** "Missing" and "weak" prompt completely different
actions from the operator, and collapsing them into one list is what makes a gap report
useless. Nothing may be marked missing merely because a keyword is absent when equivalent
evidence exists — see :class:`MatchLevel`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MatchLevel(StrEnum):
    """How well the CV evidences one requirement.

    Five levels rather than a boolean, because the operator's next action differs at each:
    ``EXCELLENT`` and ``STRONG`` are left alone, ``PARTIAL`` and ``WEAK`` are strengthened
    with wording they already have, and only ``MISSING`` means "you cannot honestly claim
    this".
    """

    EXCELLENT = "excellent"
    STRONG = "strong"
    PARTIAL = "partial"
    WEAK = "weak"
    MISSING = "missing"


class EvidenceSource(StrEnum):
    """Which part of the CV a match was found in."""

    EXPERIENCE = "experience"
    SKILLS = "skills"
    EDUCATION = "education"
    SUMMARY = "summary"
    CERTIFICATIONS = "certifications"
    PROJECTS = "projects"
    #: Found in the CV text but not attributable to a named section.
    UNATTRIBUTED = "unattributed"


class RequirementMatch(BaseModel):
    """One job requirement, and what the CV actually says about it."""

    requirement: str
    level: MatchLevel
    #: The CV text that supports this, quoted rather than summarised. Empty when MISSING.
    evidence: str = ""
    #: Where in the CV it was found. ``None`` when nothing was found.
    source: EvidenceSource | None = None
    #: The employer or institution the evidence sits under, when attributable
    #: ("CV → Experience → SimplyPhi"). Absent rather than guessed.
    source_detail: str = ""
    #: True when the match was made on meaning rather than the literal word — "led delivery"
    #: matching "delivery ownership". Surfaced so the operator can sanity-check the inference
    #: instead of trusting it blind.
    semantic: bool = False
    #: Whether the posting presented this as required or preferred. Unknown stays unknown.
    required: bool | None = None


class FitCategory(BaseModel):
    """One scored dimension of fit.

    Only emitted when the posting supplies enough to judge it. The absence of a category is
    itself information, and is reported separately in :attr:`FitAnalysis.not_assessed`.
    """

    key: str
    label: str
    score: float = Field(ge=0.0, le=1.0)
    #: Plain-English justification for the number, referencing what was compared.
    rationale: str = ""
    #: How the score was arrived at — which lets the UI answer "where did this come from".
    method: str = ""


class Recommendation(BaseModel):
    """One suggested CV change, grounded in something the operator already has.

    ``grounded_in`` is mandatory in spirit: a recommendation that cannot point at existing
    material is telling the user to invent experience. Where the honest advice is "you do not
    have this", :attr:`kind` is ``cannot_evidence`` and the text says so rather than
    suggesting they claim it.
    """

    text: str
    #: add_evidence | strengthen | reword | quantify | cannot_evidence
    kind: str = "strengthen"
    #: The requirement this addresses.
    requirement: str = ""
    #: What in the CV this builds on. Empty only for ``cannot_evidence``.
    grounded_in: str = ""


class FitAnalysis(BaseModel):
    """A complete job-vs-CV assessment."""

    job_id: str
    resume_id: str
    resume_name: str = ""
    overall: float = Field(ge=0.0, le=1.0)
    #: Scored dimensions, best first. Only those the posting supported.
    categories: list[FitCategory] = Field(default_factory=list)
    #: Dimensions deliberately not scored, with the reason — "the posting publishes no salary".
    not_assessed: list[str] = Field(default_factory=list)
    matches: list[RequirementMatch] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    #: How the requirements were obtained: ``llm`` or ``keyword`` (the deterministic
    #: fallback). Shown so a degraded analysis is never mistaken for a full one.
    method: str = "keyword"
    #: The model that produced it, when one did. Traceable to the AI configuration.
    model: str = ""
    analysed_at: datetime | None = None
    #: True when this was loaded from a previous run rather than computed now.
    cached: bool = False
    #: Set when the stored analysis was made against a different CV than the one now selected.
    stale_reason: str = ""

    @property
    def strong_matches(self) -> list[RequirementMatch]:
        return [m for m in self.matches if m.level in (MatchLevel.STRONG, MatchLevel.EXCELLENT)]

    @property
    def gaps(self) -> list[RequirementMatch]:
        return [
            m for m in self.matches
            if m.level in (MatchLevel.MISSING, MatchLevel.WEAK, MatchLevel.PARTIAL)
        ]


class FitRequest(BaseModel):
    """Analyse this CV against this job."""

    resume_id: str
    #: Recompute even if a stored analysis for this (job, resume) exists.
    refresh: bool = False
