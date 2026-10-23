"""What each target role actually wants, as weighted skills.

A role maps to a list of ``(skill_key, weight, must_have)``. Weight (1-5) drives both the
ranking in the aggregated view and the contribution to the coverage score; ``must_have`` marks
the skills a screener treats as table stakes, so the UI can separate "you are missing a
core requirement" from "this would strengthen you".

Profiles are defined for the titles people actually select, and a per-family default covers any
title not listed explicitly (the family is inferred the same way the frontend's
``familyForTitle`` does it). Weights reflect how these roles are hired in the UK AI/product
market - domain knowledge, not claims about any individual.
"""



from __future__ import annotations

import re

#: (skill_key, weight 1-5, must_have)
RoleSkill = tuple[str, int, bool]

Family = str  # "product" | "engineering" | "architecture" | "data"


def family_for_title(title: str) -> Family:
    """Mirror of the frontend's familyForTitle, so both ends bucket a title identically."""
    t = title.lower()
    if re.search(
        r"(product manager|product owner|head of product|product lead|\bapm\b|product analyst)", t
    ):
        return "product"
    if re.search(
        r"(machine learning|\bml\b|genai|llm|computer vision|\bai\b engineer|mlops|data engineer)",
        t,
    ):
        return "engineering"
    if re.search(r"(architect|consultant|solutions engineer|strategy)", t):
        return "architecture"
    if re.search(r"(scientist|analyst|analytics)", t):
        return "data"
    return "product"


# Reusable clusters, composed into profiles below.
_PM_CORE: list[RoleSkill] = [
    ("roadmap", 5, True),
    ("prioritization", 5, True),
    ("metrics", 5, True),
    ("stakeholder", 5, True),
    ("strategy", 4, True),
    ("discovery", 4, True),
    ("prd", 4, True),
    ("agile", 4, True),
    ("crossfunc", 4, True),
    ("gtm", 3, False),
    ("userstory", 3, False),
    ("ux", 3, False),
    ("comms", 3, False),
    ("delivery", 3, False),
    ("experimentation", 3, False),
    ("analytics", 3, False),
    ("sql", 2, False),
]

_AI_OVERLAY: list[RoleSkill] = [
    ("genai", 5, True),
    ("ml", 4, True),
    ("aieval", 3, False),
    ("rag", 3, False),
    ("prompteng", 3, False),
    ("aigov", 3, False),
    ("agents", 2, False),
    ("mlops", 2, False),
]

_ENG_CORE: list[RoleSkill] = [
    ("python", 5, True),
    ("ml", 5, True),
    ("mlops", 4, True),
    ("apis", 4, True),
    ("cloud", 4, True),
    ("sysdesign", 4, True),
    ("genai", 4, False),
    ("pytorch", 4, False),
    ("cicd", 3, False),
    ("docker", 3, False),
    ("sql", 3, False),
    ("rag", 3, False),
    ("nlp", 3, False),
    ("datapipe", 2, False),
    ("git", 2, False),
    ("aieval", 3, False),
]

_DATA_CORE: list[RoleSkill] = [
    ("sql", 5, True),
    ("stats", 5, True),
    ("python", 4, True),
    ("experimentation", 4, True),
    ("analytics", 4, True),
    ("dataviz", 4, True),
    ("cohort", 3, False),
    ("ml", 3, False),
    ("etl", 3, False),
    ("datamodel", 3, False),
    ("notebooks", 3, False),
    ("metrics", 3, False),
    ("comms", 3, False),
    ("stakeholder", 3, False),
]

_ARCH_CORE: list[RoleSkill] = [
    ("sysdesign", 5, True),
    ("cloud", 5, True),
    ("ml", 4, True),
    ("apis", 4, True),
    ("strategy", 4, True),
    ("stakeholder", 4, True),
    ("mlops", 4, False),
    ("genai", 4, False),
    ("sysdesign", 4, True),
    ("comms", 3, False),
    ("b2b", 3, False),
    ("delivery", 3, False),
    ("docker", 3, False),
    ("rag", 3, False),
    ("aigov", 3, False),
]


def _merge(*groups: list[RoleSkill]) -> list[RoleSkill]:
    """Combine clusters, keeping the strongest weight and the stricter must-have per skill."""
    best: dict[str, RoleSkill] = {}
    for group in groups:
        for key, weight, must in group:
            cur = best.get(key)
            if cur is None or weight > cur[1] or (weight == cur[1] and must and not cur[2]):
                best[key] = (key, weight, must or (cur[2] if cur else False))
    return list(best.values())


FAMILY_DEFAULT: dict[Family, list[RoleSkill]] = {
    "product": _PM_CORE,
    "engineering": _ENG_CORE,
    "data": _DATA_CORE,
    "architecture": _ARCH_CORE,
}

# Explicit profiles for the titles people actually pick. Anything not here falls back to family.
ROLE_PROFILES: dict[str, list[RoleSkill]] = {
    "AI Product Manager": _merge(_PM_CORE, _AI_OVERLAY),
    "AI/ML Product Manager": _merge(_PM_CORE, _AI_OVERLAY),
    "Product Manager - AI/ML": _merge(_PM_CORE, _AI_OVERLAY),
    "Technical Product Manager": _merge(
        _PM_CORE,
        [("apis", 4, True), ("sysdesign", 3, False), ("sql", 3, False), ("cloud", 3, False)],
    ),
    "Technical Product Owner": _merge(
        _PM_CORE, [("apis", 4, True), ("sysdesign", 3, False), ("agile", 5, True)]
    ),
    "AI Product Owner": _merge(_PM_CORE, _AI_OVERLAY, [("agile", 5, True)]),
    "Data Product Manager": _merge(
        _PM_CORE,
        [("sql", 4, True), ("analytics", 4, True), ("datamodel", 3, False), ("etl", 3, False)],
    ),
    "Analytics Product Manager": _merge(
        _PM_CORE,
        [
            ("sql", 4, True),
            ("analytics", 5, True),
            ("experimentation", 4, True),
            ("dataviz", 3, False),
        ],
    ),
    "Data Platform Product Manager": _merge(
        _PM_CORE,
        [("etl", 4, True), ("datamodel", 4, True), ("cloud", 3, False), ("apis", 3, False)],
    ),
    "Digital Product Manager": _PM_CORE,
    "Product Manager": _PM_CORE,
    "Associate Product Manager": _merge(
        _PM_CORE,
        [("roadmap", 4, True), ("strategy", 3, False)],  # APM: slightly less strategy weight
    ),
    "AI Program Manager": _merge(
        _PM_CORE, [("delivery", 5, True), ("crossfunc", 5, True), ("genai", 3, False)]
    ),
    "Product Analyst": _merge(
        _DATA_CORE,
        [
            ("metrics", 5, True),
            ("experimentation", 5, True),
            ("analytics", 5, True),
            ("roadmap", 2, False),
        ],
    ),
    "Data Analyst": _DATA_CORE,
    "Data Scientist": _merge(
        _DATA_CORE, [("ml", 5, True), ("stats", 5, True), ("python", 5, True)]
    ),
    "Applied Scientist": _merge(_ENG_CORE, _DATA_CORE, [("ml", 5, True), ("nlp", 4, False)]),
    "Decision Scientist": _merge(_DATA_CORE, [("stats", 5, True), ("experimentation", 5, True)]),
    "ML Engineer": _ENG_CORE,
    "Machine Learning Engineer": _ENG_CORE,
    "Applied AI Engineer": _merge(_ENG_CORE, _AI_OVERLAY),
    "AI Engineer": _merge(_ENG_CORE, _AI_OVERLAY),
    "GenAI Engineer": _merge(
        _ENG_CORE, _AI_OVERLAY, [("rag", 5, True), ("prompteng", 4, True), ("langchain", 4, False)]
    ),
    "LLM Engineer": _merge(
        _ENG_CORE, _AI_OVERLAY, [("rag", 5, True), ("langchain", 4, True), ("aieval", 4, True)]
    ),
    "MLOps Engineer": _merge(
        _ENG_CORE, [("mlops", 5, True), ("docker", 4, True), ("cicd", 4, True), ("cloud", 5, True)]
    ),
    "ML Platform Engineer": _merge(
        _ENG_CORE, [("mlops", 5, True), ("sysdesign", 4, True), ("datapipe", 4, False)]
    ),
    "Computer Vision Engineer": _merge(
        _ENG_CORE, [("cv", 5, True), ("pytorch", 5, True), ("nlp", 2, False)]
    ),
    "Data Engineer": _merge(
        _ENG_CORE,
        [("etl", 5, True), ("datapipe", 5, True), ("sql", 5, True), ("datamodel", 4, True)],
    ),
    "ML Data Engineer": _merge(
        _ENG_CORE, [("etl", 4, True), ("datapipe", 4, True), ("sql", 4, True)]
    ),
    "AI Solutions Architect": _merge(_ARCH_CORE, _AI_OVERLAY),
    "ML Solutions Architect": _merge(_ARCH_CORE, [("mlops", 5, True), ("ml", 5, True)]),
    "AI Technical Consultant": _merge(
        _ARCH_CORE, [("comms", 4, True), ("b2b", 4, True), ("genai", 4, True)]
    ),
    "Data & AI Consultant": _merge(_ARCH_CORE, _DATA_CORE, [("sql", 4, True), ("b2b", 4, True)]),
    "AI Implementation Consultant": _merge(_ARCH_CORE, [("delivery", 5, True), ("b2b", 4, True)]),
    "AI Solutions Engineer": _merge(
        _ENG_CORE, [("apis", 5, True), ("comms", 4, True), ("b2b", 3, False)]
    ),
    "Forward Deployed AI Engineer": _merge(
        _ENG_CORE, [("comms", 4, True), ("b2b", 4, True), ("delivery", 4, True)]
    ),
    "Innovation / AI Strategy Manager": _merge(
        _ARCH_CORE, [("strategy", 5, True), ("pnl", 4, True), ("genai", 4, True)]
    ),
}


def _norm(title: str) -> str:
    """Normalise a title for lookup: any dash to a hyphen, whitespace collapsed.

    The role vocab is shared with the frontend, which writes "Product Manager - AI/ML"; a
    selection arriving with an en dash must still resolve to the same profile.
    """
    t = title.replace(chr(0x2013), "-").replace(chr(0x2014), "-")  # en/em dash -> hyphen
    return re.sub(r"\s+", " ", t).strip()


def skills_for_title(title: str) -> list[RoleSkill]:
    """The weighted skill profile for one role title (explicit, else family default)."""
    exact = ROLE_PROFILES.get(_norm(title)) or ROLE_PROFILES.get(title.strip())
    if exact is not None:
        return exact
    return FAMILY_DEFAULT[family_for_title(title)]


def known_titles() -> list[str]:
    """Titles with an explicit curated profile - the Radar's suggested selections."""
    return sorted(ROLE_PROFILES)
