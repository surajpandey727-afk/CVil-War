"""The evaluator's findings in plain terms: strongest, weak, missing, problems, verdict.

(Brief sections 17–27.)

Nothing here is flattering by design. It names what holds a résumé back, says where the fix is
and states plainly when a gap cannot be closed without evidence the candidate does not have.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.ats_engine.matching import Assessment
from app.core.ats_engine.scoring import Seniority
from app.core.ats_engine.shortlist import Shortlist
from app.core.ats_engine.structure import Structure
from app.core.ats_engine.taxonomy import TIER_WEIGHT, ReqTier, Strength

#: Rough ATS points one requirement is worth at each tier (weight share of the coverage components).
_POINTS = {
    ReqTier.CRITICAL: 4.0,
    ReqTier.IMPORTANT: 2.0,
    ReqTier.SUPPORTING: 1.0,
    ReqTier.NICE: 0.5,
}


@dataclass
class Finding:
    requirement: str
    tier: str
    type: str
    strength: str
    evidence: str = ""
    location: str = ""
    note: str = ""


@dataclass
class Problem:
    what: str
    where: str
    why: str
    effect: str
    priority: str = "should"  # must | should | optional
    tailorable: bool = True


@dataclass
class Verdict:
    ats_alignment: str
    human_review: str
    why: list[str] = field(default_factory=list)
    holding_back: list[str] = field(default_factory=list)
    highest_value: list[str] = field(default_factory=list)
    tailoring_limit: str = ""


@dataclass
class Recruiter:
    signal: str
    reasons: list[str] = field(default_factory=list)


def _finding(a: Assessment, note: str = "") -> Finding:
    best = a.evidence[0] if a.evidence else None
    return Finding(
        a.requirement.term,
        a.requirement.tier.value,
        a.requirement.type.value,
        a.strength.label,
        (best.text[:160] if best else a.note),
        a.location,
        note or a.note,
    )


def strongest(assessments: list[Assessment], limit: int = 6) -> list[Finding]:
    ranked = sorted(
        (a for a in assessments if a.strength >= Strength.DEMONSTRATED),
        key=lambda a: (-TIER_WEIGHT[a.requirement.tier], -int(a.strength)),
    )
    return [_finding(a) for a in ranked[:limit]]


def weak(assessments: list[Assessment], structure: Structure) -> list[Finding]:
    out: list[Finding] = []
    for a in assessments:
        if a.requirement.tier in (ReqTier.NICE,):
            continue
        if a.strength is Strength.MENTIONED:
            out.append(_finding(a, "Listed, but no work bullet shows it."))
        elif a.strength >= Strength.SUPPORTED and a.match == "semantic":
            out.append(_finding(a, "Equivalent wording is used; the exact term is not."))
        elif (
            a.strength >= Strength.SUPPORTED
            and a.requirement.tier in (ReqTier.CRITICAL, ReqTier.IMPORTANT)
            and not a.in_top_zone
            and a.evidence
        ):
            role = a.evidence[0].role
            if role is not None and role >= 1:
                out.append(
                    _finding(
                        a, "The evidence sits in an older role, away from the top of the résumé."
                    )
                )
    return out


def missing(assessments: list[Assessment]) -> list[Finding]:
    return [
        _finding(a)
        for a in assessments
        if a.strength is Strength.NONE and a.requirement.tier is not ReqTier.NICE
    ]


def _gain(a: Assessment, to: Strength) -> str:
    from app.core.ats_engine.taxonomy import STRENGTH_CREDIT

    delta = STRENGTH_CREDIT[to] - STRENGTH_CREDIT[a.strength]
    return f"about +{max(1, round(delta * _POINTS[a.requirement.tier]))} ATS points"


def problems(
    assessments: list[Assessment],
    structure: Structure,
    senior: Seniority,
    shortlist: Shortlist,
    parsing_findings: list[str],
    quantified: float,
) -> list[Problem]:
    out: list[Problem] = []
    for a in assessments:
        if a.requirement.tier not in (ReqTier.CRITICAL, ReqTier.IMPORTANT):
            continue
        if a.strength is Strength.MENTIONED:
            out.append(
                Problem(
                    f"Show '{a.requirement.term}' in an experience bullet where it was really "
                    f"used.",
                    "Skills section only → a bullet in the most relevant role",
                    "A listed skill with no supporting work is treated as a mention, not evidence.",
                    _gain(a, Strength.SUPPORTED),
                    "must" if a.requirement.tier is ReqTier.CRITICAL else "should",
                )
            )
        elif (
            a.strength >= Strength.SUPPORTED
            and a.evidence
            and not a.in_top_zone
            and (a.evidence[0].role or 0) >= 1
        ):
            out.append(
                Problem(
                    f"Surface the strongest '{a.requirement.term}' evidence higher up.",
                    f"{a.location} → first role or summary",
                    "A reader sees the top third first; relevant evidence buried in an older "
                    "role is easy to miss.",
                    "better visibility; no change to the ATS match",
                    "should",
                    tailorable=False,
                )
            )
    if quantified < 0.2 and structure.evidence:
        out.append(
            Problem(
                "Add measurable outcomes where real figures exist.",
                "Experience bullets with no number or result",
                f"Only {round(quantified * 100)}% of bullets state a quantity or result; "
                f"outcomes separate candidates.",
                "raises impact and specificity in shortlist readiness",
                "should",
            )
        )
    for note in senior.notes[:2]:
        out.append(
            Problem(
                "Close the seniority gap in how the experience is described.",
                "Experience and summary",
                note,
                "raises the seniority component",
                "should",
                tailorable=False,
            )
        )
    for finding in parsing_findings[:2]:
        out.append(
            Problem(
                "Fix a parsing risk in the file.",
                "The PDF itself",
                finding,
                "raises the parsing score",
                "must",
                tailorable=False,
            )
        )
    for note in shortlist.notes[:1]:
        out.append(
            Problem(
                "Remove credibility risks.",
                "Experience bullets",
                note,
                "raises credibility",
                "should",
            )
        )
    order = {"must": 0, "should": 1, "optional": 2}
    out.sort(key=lambda p: order[p.priority])
    return out[:7]


def recruiter_signal(
    assessments: list[Assessment], structure: Structure, senior: Seniority, quantified: float
) -> Recruiter:
    critical = [a for a in assessments if a.requirement.tier is ReqTier.CRITICAL]
    supported = sum(1 for a in critical if a.strength >= Strength.SUPPORTED)
    answers = {
        "What this candidate does is clear": bool(structure.of("summary") or structure.roles),
        "Why they fit the role shows at the top": _top_share(assessments) >= 0.5,
        "Similar work has actually been done": bool(critical) and supported / len(critical) >= 0.6,
        "The operating level matches": senior.score >= 70,
        "Measurable outcomes are present": quantified >= 0.3,
    }
    yes = sum(answers.values())
    signal = "Strong" if yes >= 4 else "Mixed" if yes >= 2 else "Weak"
    reasons = [f"{'Yes' if v else 'No'}: {k}" for k, v in answers.items()]
    return Recruiter(signal, reasons)


def _top_share(assessments: list[Assessment]) -> float:
    pool = [a for a in assessments if a.requirement.tier in (ReqTier.CRITICAL, ReqTier.IMPORTANT)]
    return (
        sum(1 for a in pool if a.in_top_zone and a.strength >= Strength.MENTIONED) / len(pool)
        if pool
        else 0.0
    )


def verdict(
    ats: int,
    shortlist: Shortlist,
    assessments: list[Assessment],
    senior: Seniority,
    issues: list[Problem],
    recoverable: frozenset[str],
) -> Verdict:
    from app.core.ats_engine.taxonomy import band

    ats_label = "Strong" if ats >= 80 else "Moderate" if ats >= 65 else "Weak"
    human = "Strong" if shortlist.score >= 75 else "Moderate" if shortlist.score >= 55 else "Weak"
    gaps = [
        a
        for a in assessments
        if a.strength is Strength.NONE
        and a.requirement.tier in (ReqTier.CRITICAL, ReqTier.IMPORTANT)
    ]
    unsupported = [a for a in gaps if a.requirement.term.lower() not in recoverable]
    strong_n = sum(1 for a in assessments if a.strength >= Strength.DEMONSTRATED)
    why = [
        f"{band(ats)} on ATS match ({ats}/100); {shortlist.score}/100 on shortlist readiness.",
        f"{strong_n} requirement(s) are demonstrated by real work.",
    ]
    if shortlist.dimensions:
        low = min(shortlist.dimensions, key=lambda k: shortlist.dimensions[k])
        why.append(
            f"Weakest human-review dimension: {low.replace('_', ' ')} "
            f"({shortlist.dimensions[low]}/100)."
        )
    if ats - shortlist.score >= 12:
        why.append(
            "ATS alignment is higher than evidence quality: terminology is covered better than "
            "it is proven."
        )
    holding = [
        f"No evidence of '{a.requirement.term}' ({a.requirement.tier.value})." for a in gaps[:5]
    ] + senior.notes[:1]
    limit = ""
    if unsupported:
        names = ", ".join(a.requirement.term for a in unsupported[:4])
        pronoun = "it" if len(unsupported) == 1 else "them"
        limit = (
            f"Further improvement is limited: the posting asks for {names} and the résumé has "
            f"no evidence of {pronoun}. Adding {pronoun} would be fabrication."
        )
    return Verdict(ats_label, human, why[:5], holding, [p.what for p in issues[:3]], limit)
