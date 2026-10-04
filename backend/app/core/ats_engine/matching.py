"""Decide how well the résumé evidences each requirement (brief sections 5–8, 10).

Presence is not evidence. "Python" in a skills list is a mention; "Python" in two experience
bullets is support; "Python" in a bullet that builds something and states the result is strong
evidence. The strength ladder is what lets the score tell a skills dump from a demonstrated one.
"""
# ruff: noqa: RUF002
# En dashes in the brief's own section references.

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.ats_engine.requirements import EvalRequirement, RequirementSet
from app.core.ats_engine.structure import Structure, Unit
from app.core.ats_engine.taxonomy import ReqType, Strength
from app.core.resume_tailoring.jobspec import equivalents

#: Equivalent spellings and abbreviations. Both directions are recognised.
_VARIANTS: tuple[tuple[str, ...], ...] = (
    ("machine learning", "ml"),
    ("artificial intelligence", "ai"),
    ("natural language processing", "nlp"),
    ("large language models", "llm", "llms"),
    ("kubernetes", "k8s"),
    ("javascript", "js"),
    ("prioritization", "prioritisation"),
    ("modeling", "modelling"),
    ("data catalog", "data catalogue"),
    ("a/b testing", "ab testing", "split testing"),
    ("ci/cd", "continuous integration"),
    ("okrs", "okr"),
    ("kpis", "kpi"),
    ("apis", "api"),
    ("power bi", "powerbi"),
    ("monetization", "monetisation"),
    ("visualization", "visualisation"),
    ("analyze", "analyse"),
    ("user stories", "user story"),
    ("stakeholder management", "stakeholder engagement"),
    ("generative ai", "gen ai", "genai"),
    ("retrieval augmented generation", "rag"),
    ("product requirements", "prd", "prds"),
    ("ux", "user experience"),
    ("e-commerce", "ecommerce"),
)
#: A line naming this many distinct requirements is a keyword list, not a description of work.
_STUFFED_AT = 7


@dataclass
class Evidence:
    line_id: str
    section: str
    text: str
    match: str  # exact | variant | semantic
    quantified: bool
    role: int | None
    position: int


@dataclass
class Assessment:
    requirement: EvalRequirement
    strength: Strength
    match: str = "none"  # best kind of match found: exact | variant | semantic | none
    evidence: list[Evidence] = field(default_factory=list)
    in_top_zone: bool = False
    recency: float = 0.0
    note: str = ""

    @property
    def location(self) -> str:
        if not self.evidence:
            return ""
        best = self.evidence[0]
        where = best.section.title()
        if best.role is not None:
            where += f" · role {best.role + 1} · bullet {best.position + 1}"
        return where


def _present(term: str, low: str) -> bool:
    return re.search(rf"(?<![\w/]){re.escape(term)}(?![\w/])", low) is not None


def _forms(term: str) -> list[str]:
    forms = {term}
    for group in _VARIANTS:
        if term in group:
            forms.update(group)
    if term.endswith("s") and len(term) > 4:
        forms.add(term[:-1])
    elif len(term) > 3 and not term.endswith("s"):
        forms.add(term + "s")
    return sorted(forms - {term}, key=len, reverse=True)


def _match_kind(req: EvalRequirement, unit: Unit) -> str | None:
    low = unit.lower
    if req.family:
        return "exact" if any(_present(w, low) for w in req.family) else None
    term = req.term.lower()
    if _present(term, low):
        return "exact"
    if any(_present(v, low) for v in _forms(term)):
        return "variant"
    if any(_present(alt, low) for alt in equivalents(term)):
        return "semantic"
    return None


def _mark_stuffed(units: list[Unit], spec: RequirementSet) -> None:
    """Flag experience lines that merely list JD terms, so nothing downstream counts them as "
    "work."""
    terms = [
        r.term.lower()
        for r in spec.items
        if not r.family
        and r.type not in (ReqType.EXPERIENCE, ReqType.EDUCATION, ReqType.CERTIFICATION)
    ]
    for unit in units:
        unit.stuffed = False
    for unit in units:
        if unit.is_evidence and sum(1 for t in terms if _present(t, unit.lower)) >= _STUFFED_AT:
            unit.stuffed = True


def _strength(evidence: list[Evidence], units: dict[str, Unit], listed: bool) -> Strength:
    experience = [e for e in evidence if units[e.line_id].is_evidence]
    if not evidence:
        return Strength.NONE
    if not experience:
        return Strength.MENTIONED
    n = len(experience)
    show = any(units[e.line_id].quantified and units[e.line_id].action for e in experience)
    fresh = max(units[e.line_id].recency for e in experience)
    only_semantic = all(e.match == "semantic" for e in experience)
    if n >= 3 or (n >= 2 and show and fresh >= 0.6):
        level = Strength.STRONG
    elif n >= 2 or show:
        level = Strength.DEMONSTRATED
    else:
        level = Strength.SUPPORTED
    if only_semantic:
        level = min(level, Strength.SUPPORTED)
    if listed and level > Strength.MENTIONED and n == 1 and not show:
        level = Strength.SUPPORTED
    return level


def assess(structure: Structure, spec: RequirementSet) -> list[Assessment]:
    """One :class:`Assessment` per requirement."""
    units = {u.line_id: u for u in structure.units}
    _mark_stuffed(structure.units, spec)
    top = {u.line_id for u in structure.top_zone}
    out: list[Assessment] = []

    for req in spec.items:
        if req.type is ReqType.EXPERIENCE:
            out.append(_years(req, structure, spec))
            continue
        if req.type is ReqType.EDUCATION:
            out.append(_degree(req, structure, spec))
            continue
        if req.type is ReqType.CERTIFICATION:
            out.append(_certification(req, structure))
            continue
        found: list[Evidence] = []
        for unit in structure.units:
            if unit.section == "education" and req.type is not ReqType.RESPONSIBILITY:
                continue
            kind = _match_kind(req, unit)
            if kind is None:
                continue
            found.append(
                Evidence(
                    unit.line_id,
                    unit.section,
                    unit.text,
                    kind,
                    unit.quantified,
                    unit.role,
                    unit.position,
                )
            )
        found.sort(
            key=lambda e: (
                e.match != "exact",
                units[e.line_id].section != "experience",
                -units[e.line_id].recency,
                -int(e.quantified),
            )
        )
        level = _strength(found, units, listed=False)
        best = found[0].match if found else "none"
        out.append(
            Assessment(
                req,
                level,
                best,
                found[:4],
                any(e.line_id in top for e in found),
                max(
                    (units[e.line_id].recency for e in found if units[e.line_id].is_evidence),
                    default=0.0,
                ),
            )
        )
    return out


def _years(req: EvalRequirement, structure: Structure, spec: RequirementSet) -> Assessment:
    have = structure.total_years
    stated = structure.stated_years or 0
    need = spec.years_required or 0
    best = max(have, float(stated))
    if need and best >= need:
        level = Strength.STRONG if have >= need else Strength.SUPPORTED
        note = f"{have:.1f} years across dated roles" + (f", {stated} stated" if stated else "")
    elif need and best >= 0.75 * need:
        level, note = Strength.SUPPORTED, f"about {best:.1f} of {need} years"
    elif best > 0:
        level, note = Strength.MENTIONED, f"{best:.1f} of {need} years"
    else:
        level, note = Strength.NONE, "no dated experience found"
    return Assessment(req, level, "exact" if level else "none", [], False, 1.0, note)


def _degree(req: EvalRequirement, structure: Structure, spec: RequirementSet) -> Assessment:
    text = " ".join(u.text for u in structure.of("education")).lower() or " ".join(
        u.lower for u in structure.units
    )
    have = (
        3
        if re.search(r"\b(phd|doctorate|dphil)\b", text)
        else 2
        if re.search(r"\b(msc|m\.sc|master|mba|ma\b|meng)", text)
        else 1
        if re.search(
            r"\b(bsc|b\.sc|bachelor|ba\b|beng|be\b|btech|b\.tech|degree|university|college)\b", text
        )
        else 0
    )
    level = (
        Strength.STRONG
        if have >= spec.degree_level
        else Strength.MENTIONED
        if have
        else Strength.NONE
    )
    return Assessment(
        req,
        level,
        "exact" if level else "none",
        [],
        False,
        1.0,
        f"degree level {have} vs {spec.degree_level} asked",
    )


def _certification(req: EvalRequirement, structure: Structure) -> Assessment:
    needle = req.term.lower()
    hit = next((u for u in structure.units if needle in u.lower), None)
    if hit is None:
        return Assessment(req, Strength.NONE)
    ev = Evidence(
        hit.line_id, hit.section, hit.text, "exact", hit.quantified, hit.role, hit.position
    )
    return Assessment(req, Strength.STRONG, "exact", [ev], True, 1.0)
