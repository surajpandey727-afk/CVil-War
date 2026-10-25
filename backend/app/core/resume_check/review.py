"""Claude's narrative review, layered on the deterministic check — and never trusted blindly.

The model writes prose and proposes rewrites. Everything it returns is validated before use:
the JSON must match :class:`LlmReview`; each note/suggestion must name a known section; every
rewrite's ``original`` must be a verbatim line of the résumé (no "rewriting" text the candidate
never wrote); and every suggestion's evidence status is decided here by
:func:`suggest.evidence_status`, not by the model. An item that fails is dropped and counted.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.core.resume_check.suggest import evidence_status
from app.core.resume_check.text import contains_verbatim
from app.schemas.resume_check import (
    ResumeCheckResponse,
    SectionNote,
    Suggestion,
)

SECTIONS = ("summary", "experience", "skills", "formatting")
#: Résumés are short; this is a guard against a pathological extraction, and it is stated in
#: the prompt rather than applied silently.
MAX_RESUME_CHARS = 30_000

SYSTEM_PROMPT = """You are a senior UK recruiter and CV editor reviewing one candidate's CV
against one target. You receive the CV text and a deterministic analysis (already-computed
scores, matched and missing skills, section findings). Do not recompute or contradict the
numbers; explain them and say what to change.

Experience policy — absolute:
- Never invent employers, job titles, dates, qualifications, certifications, tools, clients or
  metrics. Use only facts present in the CV text.
- When a rewrite would be stronger with information the CV does not contain (a number, an
  outcome, a tool), write a bracketed placeholder such as [metric] or [outcome] instead of a
  value. Never fill one in.
- Every rewrite's "original" must be copied exactly, character for character, from the CV.
- Write in UK English. Be specific and brief."""

TASK = """Return ONLY a JSON object with this shape:
{{
  "summary": "3-5 sentences: overall verdict for this target and the two highest-value fixes",
  "section_notes": [{{"section": "summary|experience|skills|formatting", "note": "..."}}],
  "rewrites": [{{"section": "summary|experience|skills",
                 "original": "exact line from the CV",
                 "suggested": "rewritten line",
                 "reason": "why it is stronger"}}]
}}
At most one note per section and at most 6 rewrites, weakest lines first.

TARGET: {target}

DETERMINISTIC ANALYSIS:
{analysis}

CV TEXT{truncated}:
<<<
{resume}
>>>"""


class _Note(BaseModel):
    section: str
    note: str = Field(max_length=1200)


class _Rewrite(BaseModel):
    section: str
    original: str = Field(max_length=1500)
    suggested: str = Field(max_length=1500)
    reason: str = Field(max_length=600)


class LlmReview(BaseModel):
    summary: str = Field(max_length=2500)
    section_notes: list[_Note] = Field(default_factory=list, max_length=8)
    rewrites: list[_Rewrite] = Field(default_factory=list, max_length=12)


def build_prompt(check: ResumeCheckResponse, resume_text: str) -> str:
    target = check.target.title + (f" at {check.target.company}" if check.target.company else "")
    if check.target.kind == "roles":
        target = "Skill Radar roles: " + ", ".join(check.target.role_titles)
    analysis = {
        "overall": check.score.overall,
        "band": check.score.band,
        "components": [{c.key: c.score} for c in check.score.components],
        "matched": [m.label for m in check.matched_skills],
        "missing_must_have": [m.label for m in check.missing_skills if m.must_have],
        "missing_nice_to_have": [m.label for m in check.missing_skills if not m.must_have],
        "sections": {s.key: s.findings for s in check.sections},
    }
    truncated = ""
    if len(resume_text) > MAX_RESUME_CHARS:
        truncated = " (truncated to the first 30,000 characters)"
    return TASK.format(
        target=target,
        analysis=json.dumps(analysis, ensure_ascii=False),
        truncated=truncated,
        resume=resume_text[:MAX_RESUME_CHARS],
    )


def validate_review(
    review: LlmReview, resume_text: str
) -> tuple[list[SectionNote], list[Suggestion], int]:
    """Keep only what the policy allows. Returns (notes, suggestions, rejected_count)."""
    rejected = 0
    notes: list[SectionNote] = []
    seen_sections: set[str] = set()
    for n in review.section_notes:
        if n.section not in SECTIONS or n.section in seen_sections or not n.note.strip():
            rejected += 1
            continue
        seen_sections.add(n.section)
        notes.append(SectionNote(section=n.section, note=n.note.strip()))  # type: ignore[arg-type]

    suggestions: list[Suggestion] = []
    for r in review.rewrites[:6]:
        if (
            r.section not in SECTIONS
            or not r.suggested.strip()
            or not contains_verbatim(resume_text, r.original)
        ):
            rejected += 1
            continue
        suggestions.append(
            Suggestion(
                section=r.section,  # type: ignore[arg-type]
                kind="rewrite",
                original=r.original.strip(),
                suggested=r.suggested.strip(),
                reason=r.reason.strip(),
                evidence_status=evidence_status(r.suggested, resume_text),  # type: ignore[arg-type]
                source="llm",
            )
        )
    rejected += max(0, len(review.rewrites) - 6)
    return notes, suggestions, rejected
