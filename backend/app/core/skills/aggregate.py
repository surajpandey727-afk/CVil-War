"""Aggregate the skills a set of roles wants, and score a résumé against them.

Two operations, both pure and deterministic:

* :func:`aggregate` - merge several role profiles into one ranked demand list. A skill rises by
  how many of the selected roles want it and how heavily, so the roles the candidate actually
  picked drive the ranking, not a fixed global order.
* :func:`match_resume` - read a résumé's text once and report coverage: which wanted skills are
  present, which are missing, the weighted coverage score on a 0-1 scale (the API's convention -
  multiply by 100 to display), and the highest-value skills to add next.

Matching is word-boundary and case-insensitive, and honours a skill's surface forms, so
"experimentation" counts for the A/B-testing skill and "sql" does not fire inside "mysql". This
mirrors how ``core/ats_engine/matching.py`` decides a term is present, kept self-contained here
so the Radar does not depend on the full requirement-evaluation machinery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.skills.catalog import SKILLS, Category, Skill
from app.core.skills.roles import skills_for_title

#: A résumé that clears this fraction of weighted demand is "decent - most skills covered", the
#: band the owner asked for. Below the floor is a real gap; at/above the ceiling is strong.
DECENT_FLOOR = 0.60
STRONG_CEILING = 0.70


@dataclass(frozen=True)
class AggregatedSkill:
    skill: Skill
    #: Summed weight across the selected roles that want this skill.
    demand: int
    #: How many of the selected roles want it (the headline "N of M roles" signal).
    roles_wanting: int
    #: True if any selected role treats it as a core requirement.
    must_have: bool
    #: Live posting frequency when the job corpus was supplied, else ``None`` (not zero -
    #: "we didn't look" is different from "no posting mentions it").
    corpus_count: int | None = None


def aggregate(
    titles: list[str], corpus_counts: dict[str, int] | None = None
) -> list[AggregatedSkill]:
    """Merge the selected roles into one ranked demand list, strongest demand first."""
    demand: dict[str, int] = {}
    roles_wanting: dict[str, int] = {}
    must: dict[str, bool] = {}

    for title in titles:
        for key, weight, is_must in skills_for_title(title):
            if key not in SKILLS:
                continue
            demand[key] = demand.get(key, 0) + weight
            roles_wanting[key] = roles_wanting.get(key, 0) + 1
            must[key] = must.get(key, False) or is_must

    out = [
        AggregatedSkill(
            skill=SKILLS[key],
            demand=demand[key],
            roles_wanting=roles_wanting[key],
            must_have=must[key],
            corpus_count=(corpus_counts or {}).get(key),
        )
        for key in demand
    ]
    # Most-wanted first: by number of roles, then total weight, then must-have, then label so
    # the order is stable across identical inputs.
    out.sort(key=lambda a: (-a.roles_wanting, -a.demand, not a.must_have, a.skill.label))
    return out


def _present(skill: Skill, low_text: str) -> str | None:
    """Return the surface form that matched, or ``None``. Word-boundary, case-insensitive.

    The boundary is alphanumeric only (``[a-z0-9]``), not ``\\w``/``/``: a résumé writes
    "Agile/Scrum", "CI/CD", "A/B testing", and a slash must count as a boundary, not block the
    match. It still rejects substrings - "sql" inside "mysql", "ml" inside "html" - because the
    character on the far side is a letter. Text is pre-lowercased, so the class is safe.
    """
    for form in skill.surface_forms():
        for variant in _variants(form):
            if re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", low_text):
                return form
    return None


def _variants(form: str) -> set[str]:
    """A surface form plus its simple singular/plural, for single-token forms only.

    "prd" also matches "prds", "roadmap" also "roadmaps". Skipped for multi-word or punctuated
    forms ("a/b testing", "product roadmap") where a blanket +s would be wrong.
    """
    out = {form}
    if form.isalnum() and len(form) >= 3:
        out.add(form + "s")
        if form.endswith("s"):
            out.add(form[:-1])
    return out


@dataclass(frozen=True)
class SkillHit:
    skill: Skill
    demand: int
    roles_wanting: int
    must_have: bool
    present: bool
    matched_form: str | None


@dataclass(frozen=True)
class MatchReport:
    #: 0-1 weighted coverage (matched demand / total demand). Multiply by 100 to display.
    score: float
    #: 0-1 coverage of the must-have skills only - a strong score that hides a missing core
    #: requirement is worse than an honest middling one, so this is reported separately.
    must_have_score: float
    band: str  # "strong" | "decent" | "gap"
    hits: list[SkillHit]
    #: Highest-value missing skills, must-haves first - the "add these next" list.
    top_to_add: list[SkillHit]

    @property
    def matched(self) -> list[SkillHit]:
        return [h for h in self.hits if h.present]

    @property
    def missing(self) -> list[SkillHit]:
        return [h for h in self.hits if not h.present]


def _band(score: float) -> str:
    if score >= STRONG_CEILING:
        return "strong"
    if score >= DECENT_FLOOR:
        return "decent"
    return "gap"


def match_resume(
    resume_text: str, titles: list[str], corpus_counts: dict[str, int] | None = None
) -> MatchReport:
    """Score ``resume_text`` against the skills the selected roles want."""
    agg = aggregate(titles, corpus_counts)
    low = (resume_text or "").lower()

    hits: list[SkillHit] = []
    for a in agg:
        form = _present(a.skill, low)
        hits.append(
            SkillHit(
                skill=a.skill,
                demand=a.demand,
                roles_wanting=a.roles_wanting,
                must_have=a.must_have,
                present=form is not None,
                matched_form=form,
            )
        )

    total = sum(h.demand for h in hits) or 1
    got = sum(h.demand for h in hits if h.present)
    must_total = sum(h.demand for h in hits if h.must_have) or 1
    must_got = sum(h.demand for h in hits if h.must_have and h.present)

    score = got / total
    must_score = must_got / must_total

    # Add-these-next: missing skills, the ones a must-have and highest-demand first.
    missing = [h for h in hits if not h.present]
    missing.sort(key=lambda h: (not h.must_have, -h.demand, -h.roles_wanting))

    return MatchReport(
        score=round(score, 4),
        must_have_score=round(must_score, 4),
        band=_band(score),
        hits=hits,
        top_to_add=missing[:8],
    )


def categories_in_order() -> list[str]:
    return list(Category.ORDER)
