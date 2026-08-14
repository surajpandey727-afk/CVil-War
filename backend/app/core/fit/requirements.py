"""Getting a job's requirements out of its advert, and matching them to a CV.

Two routes, because the product must work with and without an LLM.

**LLM route** — the posting and the CV go to the model, which returns requirements with
quoted CV evidence. The model is asked to *find and quote*, never to score: scoring happens
in :mod:`app.core.fit.analyzer` from the levels it returns, because a model asked for a
percentage produces a confident one whether or not it has grounds.

**Keyword route** — no LLM configured, or the call failed. Requirements come from the
posting's own tagged skills and from the existing 49-term skill vocabulary found in the
description; matching is literal. Weaker, and it says so: the analysis reports
``method="keyword"`` so a degraded result is never presented as a full one.

The prompt's single most important instruction is the one forbidding invention. It is
reinforced structurally: the schema has a MISSING level, the model is told to use it, and
:func:`app.core.fit.analyzer.verify_matches` independently drops any quote that is not in the
CV. Three layers, because this is the failure that would make the product actively harmful —
telling someone they have experience they do not, just before they send it to an employer.
"""

from __future__ import annotations

import re

import structlog
from pydantic import BaseModel, Field

from app.core.ats.skill_matcher import SKILL_VARIATIONS
from app.schemas.fit import MatchLevel, RequirementMatch

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = (
    "You analyse how well a candidate's CV evidences a job's requirements.\n"
    "\n"
    "ABSOLUTE RULE: never invent experience, skills, employers, dates or numbers. You are "
    "reading a CV, not writing one. If the CV does not evidence a requirement, mark it "
    "'missing' — that is a correct and useful answer, not a failure.\n"
    "\n"
    "For every requirement you extract from the posting:\n"
    "  - Quote the CV text that evidences it, VERBATIM. Copy the characters exactly; do not "
    "paraphrase, tidy, translate or summarise. A quote that does not appear in the CV "
    "word-for-word will be rejected and the requirement recorded as missing.\n"
    "  - Choose a level honestly: 'excellent' (clear, quantified, central to a role), "
    "'strong' (clearly evidenced), 'partial' (adjacent or implied), 'weak' (mentioned in "
    "passing), 'missing' (no evidence).\n"
    "  - Set semantic=true when you matched meaning rather than the literal word, so a human "
    "can check your inference.\n"
    "  - Set required=true for must-haves, false for nice-to-haves, and leave it unset if the "
    "posting does not distinguish them. Do not guess.\n"
    "\n"
    "Extract 8-16 requirements: the ones that would actually decide this hire. Prefer "
    "concrete capabilities over generic filler like 'good communication skills'.\n"
    "\n"
    # Observed against the live gateway: schema injection alone was not enough. The model
    # returned a markdown comparison table, parsing failed, and the analysis silently
    # degraded to keyword matching. Stating the format — and the consequence — fixes it.
    "OUTPUT FORMAT: return ONLY a single JSON object matching the schema. No preamble, no "
    "explanation, no markdown, no tables, no code fences. The first character of your reply "
    "must be '{'. A reply containing a markdown table is discarded entirely and the analysis "
    "falls back to keyword matching, which is worse for the user."
)


class _LlmMatch(BaseModel):
    """One requirement as the model returns it, before verification."""

    requirement: str
    level: str = "missing"
    evidence: str = ""
    semantic: bool = False
    required: bool | None = None


class _LlmResult(BaseModel):
    """The structured output contract for the extraction call."""

    matches: list[_LlmMatch] = Field(default_factory=list)
    #: The model's own read of the posting's seniority, used only where the posting states one.
    seniority: str = ""


def render_prompt(*, title: str, company: str, description: str, cv_text: str) -> str:
    """Assemble the analysis prompt.

    Both texts are truncated: postings and CVs are occasionally enormous, and a request that
    overruns the model's context fails outright rather than degrading. The CV is given the
    larger share because the evidence has to come out of it.
    """
    return (
        f"JOB TITLE: {title}\n"
        f"COMPANY: {company}\n\n"
        f"JOB POSTING:\n{(description or '').strip()[:12000]}\n\n"
        f"CANDIDATE CV:\n{(cv_text or '').strip()[:14000]}\n\n"
        "Extract the requirements from the posting and, for each, quote the CV evidence "
        "verbatim or mark it missing."
    )


def to_matches(result: _LlmResult) -> list[RequirementMatch]:
    """Convert the model's output into the domain shape, coercing anything unrecognised."""
    valid = {level.value for level in MatchLevel}
    out: list[RequirementMatch] = []
    for row in result.matches:
        requirement = (row.requirement or "").strip()
        if not requirement:
            continue
        level = row.level.strip().casefold()
        out.append(RequirementMatch(
            requirement=requirement[:200],
            # An unrecognised level is treated as missing, not as a pass. A model that
            # invents a level must not thereby invent a match.
            level=MatchLevel(level) if level in valid else MatchLevel.MISSING,
            evidence=(row.evidence or "").strip()[:400],
            semantic=bool(row.semantic),
            required=row.required,
        ))
    return out


# -- Deterministic fallback -------------------------------------------------------------

#: Lines that read like requirements. Postings bullet them far more often than not.
_BULLET = re.compile(r"^\s*[-*•·▪]\s*(.{8,180})$", re.M)
_REQUIREMENT_CUE = re.compile(
    r"\b(experience|proficien|familiar|knowledge|degree|skilled|expert|background|"
    r"ability to|proven|track record|understanding of)\b", re.I
)


def keyword_requirements(
    *, description: str, tagged_skills: list[str], cv_text: str
) -> list[RequirementMatch]:
    """Requirements and matches without an LLM.

    Two sources, in order of reliability: the skills the board itself tagged on the posting
    (structured, no parsing), then vocabulary terms found in the description. Bullet lines are
    used only to enrich the requirement's wording, never as requirements on their own — a
    posting's bullets include plenty that is not a requirement at all.

    Matching is literal whole-word containment. That is genuinely weaker than the LLM route,
    which is exactly why the caller labels the result ``keyword``.
    """
    description_lower = (description or "").casefold()

    terms: list[str] = []
    for skill in tagged_skills:
        cleaned = str(skill).strip()
        if cleaned and cleaned.casefold() not in {t.casefold() for t in terms}:
            terms.append(cleaned)

    for canonical, variations in SKILL_VARIATIONS.items():
        if canonical.casefold() in {t.casefold() for t in terms}:
            continue
        if _word_in(description_lower, canonical) or any(
            _word_in(description_lower, v) for v in variations
        ):
            terms.append(canonical)

    bullets = [b.strip() for b in _BULLET.findall(description or "") if _REQUIREMENT_CUE.search(b)]

    matches: list[RequirementMatch] = []
    for term in terms[:16]:
        evidence = _find_evidence(cv_text, term)
        matches.append(RequirementMatch(
            requirement=_phrase_for(term, bullets),
            level=MatchLevel.STRONG if evidence else MatchLevel.MISSING,
            evidence=evidence,
            semantic=False,
            required=None,
        ))
    return matches


def _word_in(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(needle.casefold())}(?!\w)", haystack) is not None


def _find_evidence(cv_text: str, term: str) -> str:
    """The CV sentence containing ``term``, quoted verbatim, or empty."""
    if not cv_text:
        return ""
    for line in re.split(r"[\n.;]+", cv_text):
        if _word_in(line.casefold(), term):
            return line.strip()[:400]
    return ""


def _phrase_for(term: str, bullets: list[str]) -> str:
    """Prefer the posting's own wording for a requirement over the bare vocabulary term."""
    for bullet in bullets:
        if _word_in(bullet.casefold(), term):
            return bullet[:200]
    return term
