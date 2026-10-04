"""Turn assessments into the ATS match score and its components (brief sections 9, 15).

Every number is reproducible from the résumé, the posting and the date. The headline is a
weighted sum of eight published components; none of them is a keyword count. A requirement earns
credit in proportion to the strength of its evidence, so thirty keywords listed under Skills earn
less than ten demonstrated in experience.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from app.core.ats_engine.matching import Assessment
from app.core.ats_engine.requirements import RequirementSet, _title_seniority
from app.core.ats_engine.structure import Structure, leadership_signals
from app.core.ats_engine.taxonomy import (
    ATS_WEIGHTS,
    STRENGTH_CREDIT,
    TIER_WEIGHT,
    ReqTier,
    ReqType,
    Strength,
)

_MATCH_FACTOR = {"exact": 1.0, "variant": 0.97, "semantic": 0.88, "none": 0.0}
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
        "you",
        "your",
        "our",
        "we",
        "their",
        "they",
        "this",
        "these",
        "those",
        "will",
        "can",
        "not",
        "but",
        "if",
        "then",
        "than",
        "so",
        "such",
        "who",
        "what",
        "when",
        "where",
        "which",
        "while",
        "across",
        "about",
        "over",
        "under",
        "more",
        "most",
        "other",
        "also",
        "able",
        "including",
        "include",
        "within",
        "using",
        "use",
        "used",
        "etc",
        "per",
        "via",
    ]
)
_SKILL_TYPES = {
    ReqType.TECHNOLOGY,
    ReqType.TOOL,
    ReqType.SKILL,
    ReqType.METHODOLOGY,
    ReqType.DOMAIN,
    ReqType.BEHAVIOUR,
}


def credit(a: Assessment) -> float:
    """How much of a requirement's weight its evidence earns."""
    base = STRENGTH_CREDIT[a.strength] * _MATCH_FACTOR.get(a.match, 1.0 if a.strength else 0.0)
    if a.strength >= Strength.SUPPORTED and a.recency:
        base *= 0.8 + 0.2 * a.recency
    return base


def tokens(text: str) -> list[str]:
    out = []
    for word in re.findall(r"[a-z][a-z0-9+/#-]{2,}", text.lower()):
        if word in _STOP:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        out.append(word)
    return out


def _weighted(assessments: list[Assessment]) -> float:
    total = sum(TIER_WEIGHT[a.requirement.tier] for a in assessments)
    if not total:
        return 100.0
    return 100.0 * sum(TIER_WEIGHT[a.requirement.tier] * credit(a) for a in assessments) / total


def duty_alignment(
    structure: Structure, spec: RequirementSet
) -> tuple[float, list[tuple[str, float]]]:
    """How well the experience bullets answer the posting's own duties, line by line."""
    bullets = [(u, Counter(tokens(u.text))) for u in structure.evidence]
    duties = spec.duties[:: max(1, math.ceil(len(spec.duties) / 12))][:12] if spec.duties else []
    if not duties or not bullets:
        return 0.0, []
    scored: list[tuple[str, float]] = []
    for duty in duties:
        want = set(tokens(duty))
        if len(want) < 3:
            continue
        best = 0.0
        for unit, have in bullets:
            sim = sum(1 for t in want if t in have) / len(want)
            level = (
                1.0
                if sim >= 0.30
                else 0.75
                if sim >= 0.20
                else 0.5
                if sim >= 0.12
                else 0.25
                if sim >= 0.06
                else 0.0
            )
            quality = 1.0 if unit.action and (unit.quantified or len(have) >= 8) else 0.85
            best = max(best, level * quality * (0.8 + 0.2 * unit.recency))
        scored.append((duty[:120], best))
    if not scored:
        return 0.0, []
    return 100.0 * sum(s for _, s in scored) / len(scored), scored


def semantic_similarity(structure: Structure, spec: RequirementSet) -> float:
    """Cosine similarity of the posting's duties and the résumé's evidence, scaled 0-100."""
    want = Counter(t for d in spec.duties for t in tokens(d))
    have = Counter(t for u in structure.evidence for t in tokens(u.text))
    if not want or not have:
        return 0.0
    dot = sum(want[t] * have[t] for t in want)
    norm = math.sqrt(sum(v * v for v in want.values())) * math.sqrt(
        sum(v * v for v in have.values())
    )
    return min(100.0, 100.0 * (dot / norm) / 0.35) if norm else 0.0


@dataclass
class Seniority:
    score: int
    resume_level: int
    required_level: int
    notes: list[str] = field(default_factory=list)


_LEVELS = {1: "junior", 2: "mid-level", 3: "senior", 4: "lead / principal", 5: "director+"}


def seniority_match(structure: Structure, spec: RequirementSet) -> Seniority:
    """Whether the evidence reads as the level the role asks for, beyond holding the skills."""
    title_level = max((_title_seniority(r.heading, None) for r in structure.roles), default=2)
    years = max(structure.total_years, float(structure.stated_years or 0))
    years_level = 1 if years < 2 else 2 if years < 5 else 3 if years < 9 else 4 if years < 13 else 5
    leaders = leadership_signals(structure)
    level = (
        max(title_level if title_level > 2 else 0, years_level) if structure.roles else years_level
    )
    if leaders >= 6 and level < 5:
        level = max(level, min(5, years_level + 1))
    need = spec.seniority
    gap = need - level
    score = 100 if gap <= 0 else 70 if gap == 1 else 40 if gap == 2 else 15
    notes: list[str] = []
    if gap > 0:
        notes.append(
            f"The evidence reads as {_LEVELS[level]} (about {years:.0f} years, {leaders} "
            f"ownership/leadership bullets) "
            f"but the role is {_LEVELS[need]}."
        )
    if spec.years_required and years and years < 0.75 * spec.years_required:
        score = min(score, 60)
        notes.append(
            f"The role asks for {spec.years_required}+ years; the résumé shows about {years:.0f}."
        )
    if level - need >= 3:
        score = min(score, 85)
        notes.append("The résumé may read as over-qualified for this level.")
    return Seniority(score, level, need, notes)


def components(
    assessments: list[Assessment], structure: Structure, spec: RequirementSet, parsing_score: int
) -> tuple[dict[str, int], Seniority, list[tuple[str, float]]]:
    """The eight published components, 0-100 each."""
    by_tier = {t: [a for a in assessments if a.requirement.tier is t] for t in ReqTier}
    coverage = _weighted(assessments)
    critical = by_tier[ReqTier.CRITICAL]
    critical_cov = (
        100.0 * sum(credit(a) for a in critical) / len(critical) if critical else coverage
    )

    duty_score, duty_detail = duty_alignment(structure, spec)
    resp = [a for a in assessments if a.requirement.type is ReqType.RESPONSIBILITY]
    years = next((a for a in assessments if a.requirement.type is ReqType.EXPERIENCE), None)
    parts, weights = [], []
    if duty_detail:
        parts.append(duty_score)
        weights.append(0.60)
    if resp:
        parts.append(100.0 * sum(credit(a) for a in resp) / len(resp))
        weights.append(0.25)
    if years:
        parts.append(100.0 * credit(years))
        weights.append(0.15)
    experience = (
        sum(p * w for p, w in zip(parts, weights, strict=True)) / sum(weights)
        if parts
        else coverage
    )

    skills = [a for a in assessments if a.requirement.type in _SKILL_TYPES]
    skill = _weighted(skills) if skills else coverage
    edu = [
        a for a in assessments if a.requirement.type in (ReqType.EDUCATION, ReqType.CERTIFICATION)
    ]
    education = 100.0 * sum(credit(a) for a in edu) / len(edu) if edu else 100.0

    senior = seniority_match(structure, spec)
    values = {
        "requirement_coverage": coverage,
        "critical_coverage": critical_cov,
        "experience_responsibility": experience,
        "skill_technology": skill,
        "semantic_match": semantic_similarity(structure, spec) if spec.duties else coverage,
        "seniority": float(senior.score),
        "education_certification": education,
        "parsing": float(parsing_score),
    }
    return {k: max(0, min(100, round(v))) for k, v in values.items()}, senior, duty_detail


def headline(parts: dict[str, int], assessments: list[Assessment]) -> tuple[int, list[str]]:
    """The weighted total, with a published cap when a critical requirement has no evidence."""
    total = round(sum(parts[k] * w for k, w in ATS_WEIGHTS.items()))
    missing = [
        a.requirement.term
        for a in assessments
        if a.requirement.tier is ReqTier.CRITICAL and a.strength is Strength.NONE
    ]
    if len(missing) >= 3:
        total = min(total, 74)
    elif missing:
        total = min(total, 84)
    return total, missing
