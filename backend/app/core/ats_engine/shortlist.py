"""Shortlist readiness: how competitive the résumé is once a person reads it (brief section 16).

A different question from the ATS match. A résumé can name every required skill and still read as
junior, vague or padded; this score measures what a recruiter skimming for 10-20 seconds would
find. Ten dimensions, each computed from observable text: no model, no opinion.
"""
# ruff: noqa: E501
# A single regex literal.

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from app.core.ats_engine.matching import Assessment
from app.core.ats_engine.requirements import RequirementSet
from app.core.ats_engine.scoring import Seniority, credit, tokens
from app.core.ats_engine.structure import Structure, Unit
from app.core.ats_engine.taxonomy import SHORTLIST_WEIGHTS, TIER_WEIGHT, ReqTier, Strength

_PASSIVE = re.compile(
    r"\b(was|were|been|being)\s+(responsible|involved|tasked)|duties (included|were)|responsible for\b",
    re.I,
)
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-zA-Z0-9+#.]{2,}\b")


@dataclass
class Shortlist:
    score: int
    dimensions: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _share(count: int, total: int) -> float:
    return count / total if total else 0.0


def _bullets(structure: Structure) -> list[Unit]:
    return [u for u in structure.evidence if len(u.text.split()) >= 3]


def _relevance(assessments: list[Assessment]) -> float:
    pool = [a for a in assessments if a.requirement.tier in (ReqTier.CRITICAL, ReqTier.IMPORTANT)]
    total = sum(TIER_WEIGHT[a.requirement.tier] for a in pool)
    if not total:
        return 70.0
    seen = sum(
        TIER_WEIGHT[a.requirement.tier]
        for a in pool
        if a.in_top_zone and a.strength >= Strength.MENTIONED
    )
    return 100.0 * seen / total


def _evidence_strength(assessments: list[Assessment]) -> float:
    pool = [a for a in assessments if a.requirement.tier in (ReqTier.CRITICAL, ReqTier.IMPORTANT)]
    total = sum(TIER_WEIGHT[a.requirement.tier] for a in pool)
    if not total:
        return 70.0
    return 100.0 * sum(TIER_WEIGHT[a.requirement.tier] * credit(a) for a in pool) / total


def _impact(bullets: list[Unit]) -> float:
    if not bullets:
        return 0.0
    q = _share(sum(1 for u in bullets if u.quantified), len(bullets))
    a = _share(sum(1 for u in bullets if u.action), len(bullets))
    return 100.0 * min(1.0, 0.6 * min(1.0, q / 0.35) + 0.4 * min(1.0, a / 0.8))


def _clarity(bullets: list[Unit]) -> float:
    if not bullets:
        return 0.0
    lengths = [len(u.text.split()) for u in bullets]
    good = sum(1 for n in lengths if 8 <= n <= 35)
    long = sum(1 for n in lengths if n > 45)
    return max(0.0, 100.0 * _share(good, len(lengths)) - 12 * long)


def _credibility(structure: Structure, assessments: list[Assessment]) -> tuple[float, list[str]]:
    from app.core.resume_tailoring.plan import BANNED_PHRASES

    notes: list[str] = []
    score = 100.0
    text = " ".join(u.lower for u in structure.evidence)
    hits = [p for p in BANNED_PHRASES if p in text]
    if hits:
        score -= min(30, 6 * len(hits))
        notes.append("Machine-sounding phrases: " + ", ".join(hits[:3]))
    pool = [
        a
        for a in assessments
        if a.requirement.tier in (ReqTier.CRITICAL, ReqTier.IMPORTANT)
        and a.strength > Strength.NONE
    ]
    if pool and _share(sum(1 for a in pool if a.strength is Strength.MENTIONED), len(pool)) > 0.5:
        score -= 15
        notes.append("More than half the matched requirements appear only as listed skills.")
    wild = [u for u in structure.evidence if re.search(r"\b\d{4,}\s?%|\b[2-9]\d{2}\s?%", u.text)]
    if wild:
        score -= 20
        notes.append("Implausibly large percentages weaken credibility.")
    return max(0.0, score), notes


def _readability(bullets: list[Unit], structure: Structure) -> float:
    if not bullets:
        return 0.0
    passive = sum(1 for u in bullets if _PASSIVE.search(u.text))
    words = sum(len(u.text.split()) for u in structure.units)
    score = 100.0 - 15 * passive
    if words < 250 or words > 1100:
        score -= 20
    return max(0.0, score)


def _positioning(structure: Structure, spec: RequirementSet) -> float:
    want = set(tokens(spec.title))
    if not want:
        return 70.0
    zone = (
        " ".join(u.text for u in structure.of("header", "summary"))
        + " "
        + " ".join(r.heading for r in structure.roles)
    )
    have = set(tokens(zone))
    score = 100.0 * _share(len(want & have), len(want))
    return min(100.0, score + (10 if structure.of("summary") else 0))


def _coherence(structure: Structure) -> float:
    dated = sorted((r for r in structure.roles if r.start and r.end), key=lambda r: r.start)  # type: ignore[arg-type,return-value]
    if not dated:
        return 50.0
    score = 100.0
    for a, b in zip(dated, dated[1:], strict=False):
        gap = (b.start[0] * 12 + b.start[1]) - (a.end[0] * 12 + a.end[1])  # type: ignore[index]
        if gap > 12:
            score -= 15
    return max(0.0, score)


def _specificity(bullets: list[Unit]) -> float:
    if not bullets:
        return 0.0
    counts = [
        (1 if re.search(r"\d", u.text) else 0) + min(3, len(_PROPER.findall(u.text)))
        for u in bullets
    ]
    return min(100.0, 100.0 * statistics.mean(counts) / 2.0)


def shortlist_readiness(
    structure: Structure, assessments: list[Assessment], spec: RequirementSet, senior: Seniority
) -> Shortlist:
    bullets = _bullets(structure)
    credibility, notes = _credibility(structure, assessments)
    raw = {
        "relevance": _relevance(assessments),
        "evidence_strength": _evidence_strength(assessments),
        "impact": _impact(bullets),
        "seniority": float(senior.score),
        "clarity": _clarity(bullets),
        "credibility": credibility,
        "readability": _readability(bullets, structure),
        "role_positioning": _positioning(structure, spec),
        "career_coherence": _coherence(structure),
        "specificity": _specificity(bullets),
    }
    dims = {k: max(0, min(100, round(v))) for k, v in raw.items()}
    total = round(sum(dims[k] * w for k, w in SHORTLIST_WEIGHTS.items()))
    return Shortlist(total, dims, notes + senior.notes)


def quantified_share(structure: Structure) -> float:
    bullets = _bullets(structure)
    return _share(sum(1 for u in bullets if u.quantified), len(bullets))


__all__ = ["Shortlist", "quantified_share", "shortlist_readiness"]
