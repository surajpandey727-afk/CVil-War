"""The vocabulary of the ATS evaluation engine: tiers, requirement types, evidence strength.

Kept apart from the logic so the weights are visible in one place. They are published in every
result (``Evaluation.weights``) so a score can always be traced back to its arithmetic.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class ReqTier(StrEnum):
    """How much a missing requirement should hurt (brief section 3)."""

    CRITICAL = "critical"
    IMPORTANT = "important"
    SUPPORTING = "supporting"
    NICE = "nice_to_have"


class ReqType(StrEnum):
    """What kind of thing the requirement is (brief section 4)."""

    TECHNOLOGY = "TECHNOLOGY"
    SKILL = "SKILL"
    RESPONSIBILITY = "RESPONSIBILITY"
    DOMAIN = "DOMAIN"
    SENIORITY = "SENIORITY"
    EDUCATION = "EDUCATION"
    CERTIFICATION = "CERTIFICATION"
    TOOL = "TOOL"
    METHODOLOGY = "METHODOLOGY"
    INDUSTRY = "INDUSTRY"
    BEHAVIOUR = "BEHAVIOUR"
    LOCATION = "LOCATION"
    EXPERIENCE = "EXPERIENCE"
    OTHER = "OTHER"


class Strength(IntEnum):
    """How well the résumé evidences a requirement (brief section 6)."""

    NONE = 0
    MENTIONED = 1
    SUPPORTED = 2
    DEMONSTRATED = 3
    STRONG = 4

    @property
    def label(self) -> str:
        return self.name.replace("STRONG", "STRONGLY DEMONSTRATED")


#: A missing critical requirement costs eight times what a missing nice-to-have does.
TIER_WEIGHT: dict[ReqTier, float] = {
    ReqTier.CRITICAL: 8.0,
    ReqTier.IMPORTANT: 4.0,
    ReqTier.SUPPORTING: 2.0,
    ReqTier.NICE: 1.0,
}

#: How much of a requirement's weight each strength earns. A skill listed with no evidence
#: earns under a third; one shown repeatedly, with outcomes, earns all of it.
STRENGTH_CREDIT: dict[Strength, float] = {
    Strength.NONE: 0.0,
    Strength.MENTIONED: 0.30,
    Strength.SUPPORTED: 0.65,
    Strength.DEMONSTRATED: 0.88,
    Strength.STRONG: 1.0,
}

#: The headline score's components and their weights (brief section 15). Sums to 1.0.
ATS_WEIGHTS: dict[str, float] = {
    "requirement_coverage": 0.25,
    "critical_coverage": 0.20,
    "experience_responsibility": 0.20,
    "skill_technology": 0.15,
    "semantic_match": 0.05,
    "seniority": 0.05,
    "education_certification": 0.05,
    "parsing": 0.05,
}

#: Shortlist-readiness dimensions (brief section 16). Sums to 1.0.
SHORTLIST_WEIGHTS: dict[str, float] = {
    "relevance": 0.15,
    "evidence_strength": 0.15,
    "impact": 0.12,
    "seniority": 0.10,
    "clarity": 0.08,
    "credibility": 0.10,
    "readability": 0.06,
    "role_positioning": 0.08,
    "career_coherence": 0.06,
    "specificity": 0.10,
}

#: Interpretation bands (brief section 22). They describe alignment, never a hiring outcome.
BANDS: tuple[tuple[int, str], ...] = (
    (90, "Very strong alignment"),
    (80, "Strong alignment"),
    (70, "Moderate alignment"),
    (60, "Weak alignment"),
    (0, "Limited alignment"),
)


def band(score: int) -> str:
    return next(label for floor, label in BANDS if score >= floor)


#: Term -> type, for the skills the extractor knows. Anything unlisted is classified by shape.
TECHNOLOGY_TERMS = frozenset(
    [
        "python",
        "sql",
        "postgresql",
        "spark",
        "pyspark",
        "airflow",
        "dbt",
        "kafka",
        "kubernetes",
        "docker",
        "terraform",
        "ci/cd",
        "jenkins",
        "github",
        "actions",
        "aws",
        "azure",
        "gcp",
        "google",
        "cloud",
        "bigquery",
        "snowflake",
        "databricks",
        "vertex",
        "ai",
        "azure",
        "openai",
        "rest",
        "apis",
        "api",
        "design",
        "sdk",
        "microservices",
        "llm",
        "llms",
        "generative",
        "ai",
        "genai",
        "rag",
        "mlops",
        "machine",
        "learning",
        "ml",
        "nlp",
        "computer",
        "vision",
        "embeddings",
        "vector",
        "database",
        "data",
        "warehouse",
        "streaming",
        "batch",
    ]
)
METHODOLOGY_TERMS = frozenset(
    [
        "agile",
        "scrum",
        "kanban",
        "lean",
        "six",
        "sigma",
        "okrs",
        "a/b",
        "testing",
        "experimentation",
        "process",
        "mapping",
        "value",
        "stream",
        "mapping",
        "service",
        "blueprint",
        "prioritization",
        "prioritisation",
        "discovery",
    ]
)
DOMAIN_TERMS = frozenset(
    [
        "data",
        "governance",
        "data",
        "quality",
        "data",
        "lineage",
        "data",
        "catalogue",
        "data",
        "catalog",
        "metadata",
        "data",
        "mesh",
        "master",
        "data",
        "regulatory",
        "compliance",
        "governance",
        "ontology",
        "taxonomy",
        "cost-to-serve",
    ]
)
BEHAVIOUR_TERMS = frozenset(
    ["stakeholder", "management", "cross-functional", "workshops", "systems", "thinking"]
)


def classify(term: str) -> ReqType:
    """The requirement type of a skill term."""
    low = term.lower()
    if low in TECHNOLOGY_TERMS:
        return ReqType.TECHNOLOGY
    if low in METHODOLOGY_TERMS:
        return ReqType.METHODOLOGY
    if low in DOMAIN_TERMS:
        return ReqType.DOMAIN
    if low in BEHAVIOUR_TERMS:
        return ReqType.BEHAVIOUR
    if any(w in low for w in ("tools", "tooling", "platform", "dashboard")):
        return ReqType.TOOL
    return ReqType.SKILL
