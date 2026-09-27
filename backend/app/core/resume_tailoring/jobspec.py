"""Read a job description into the requirements a résumé can actually be measured against.

Deterministic on purpose. This runs on every tailoring pass and feeds the ATS score, and a
score that moves when nothing about the résumé or the posting changed is a score nobody can
debug or trust. No model call happens here.

Requirements are classified rather than pooled, because what follows depends on the class: a
mandatory requirement the candidate cannot evidence caps the achievable score and must be
reported as a gap, while a preferred one merely costs a few points. Lumping them together is
how a résumé ends up "85% matched" against a role it is disqualified from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Tier(StrEnum):
    """How badly the posting wants this."""

    MANDATORY = "mandatory"
    PREFERRED = "preferred"
    #: Mentioned in passing — context, not a bar.
    CONTEXTUAL = "contextual"


#: Headings that open the must-have block. Matched against a lowercased line.
_MANDATORY_CUES = (
    "required experience", "requirements", "who you are", "what you'll need",
    "must have", "essential", "qualifications", "you have", "minimum qualifications",
)
#: Headings that open the nice-to-have block.
_PREFERRED_CUES = (
    "desirable", "preferred", "nice to have", "bonus", "plus", "desired",
    "preferred qualifications", "it would be great",
)
#: Headings that open the duties block — responsibilities, not candidate attributes.
_RESPONSIBILITY_CUES = (
    "what you'll do", "key responsibilities", "responsibilities", "the role",
    "about the role", "your impact", "day to day",
)

#: Terms that are skills in this domain. A curated lexicon beats free n-gram mining for
#: precision: "human creativity" and "million creative artists" are noun phrases too, and a
#: keyword list containing them makes every score meaningless.
_LEXICON: tuple[str, ...] = (
    # product craft
    "product management", "product strategy", "roadmap", "product vision", "prd",
    "user stories", "acceptance criteria", "discovery", "prioritization", "prioritisation",
    "stakeholder management", "success metrics", "kpis", "okrs", "a/b testing",
    "product-led growth", "go-to-market", "user research", "customer research",
    "business case", "cost-to-serve", "cycle time", "adoption", "instrumentation",
    "feedback loops", "experimentation", "product requirements",
    # data platform
    "data platform", "data catalogue", "data catalog", "metadata", "data lineage",
    "data governance", "data quality", "data infrastructure", "data engineering",
    "data warehouse", "data pipelines", "etl", "elt", "streaming", "batch",
    "analytics", "bi", "data mesh", "data discovery", "data modelling", "data modeling",
    "schema", "ontology", "taxonomy", "master data",
    # platform / developer tools
    "platform product", "developer tools", "developer experience", "internal tooling",
    "apis", "api design", "rest", "microservices", "event-driven", "sdk", "self-service",
    "systems thinking", "platform thinking",
    # ml / ai
    "machine learning", "ml", "mlops", "llm", "llms", "generative ai", "genai",
    "rag", "retrieval augmented generation", "agents", "agentic", "copilots",
    "model evaluation", "evaluation frameworks", "human-in-the-loop", "model monitoring",
    "drift detection", "inference", "embeddings", "vector database", "semantic search",
    "nlp", "computer vision", "prompt engineering", "model performance", "hallucination",
    "ai/ml", "applied ai", "feature engineering", "model registry",
    # engineering / cloud
    "python", "sql", "postgresql", "spark", "pyspark", "airflow", "dbt", "kafka",
    "kubernetes", "docker", "terraform", "ci/cd", "jenkins", "github actions",
    "aws", "azure", "gcp", "google cloud", "bigquery", "snowflake", "databricks",
    "vertex ai", "azure openai", "cloud", "distributed systems",
    # process / ways of working
    "agile", "scrum", "kanban", "lean", "six sigma", "process mapping",
    "value stream mapping", "service blueprint", "business analysis", "process improvement",
    "workshops", "cross-functional", "regulatory", "compliance", "governance",
)

#: Legitimate equivalences: the key is satisfied by evidence of any value. These encode
#: "the résumé demonstrates this under different wording", which the brief allows, and
#: nothing else — a mapping is only added where the evidence genuinely implies the term.
_IMPLIES: dict[str, tuple[str, ...]] = {
    "ci/cd": ("jenkins", "github actions", "gitlab ci", "circleci", "automated deployment"),
    "data pipelines": ("etl", "elt", "pyspark", "airflow", "dbt", "pipeline"),
    "data infrastructure": ("data platform", "data engineering", "data warehouse"),
    "metadata": ("ontology", "taxonomy", "schema", "data catalogue", "data catalog"),
    "data governance": ("governance", "data quality", "citation validation", "compliance"),
    "data discovery": ("semantic search", "vector search", "search", "retrieval"),
    "analytics": ("bi", "reporting", "dashboards", "business analytics"),
    "llm": ("llms", "generative ai", "genai", "azure openai", "gpt", "gemini"),
    "generative ai": ("llm", "llms", "genai", "rag", "azure openai"),
    "agents": ("agentic", "multi-agent", "copilots"),
    "rag": ("retrieval augmented generation", "hybrid rag", "semantic retrieval"),
    "model evaluation": ("evaluation", "recall@10", "model performance", "confidence scoring"),
    "evaluation frameworks": ("model evaluation", "evaluation", "confidence scoring"),
    "human-in-the-loop": ("review", "human review", "approval", "escalation"),
    "vector database": ("chromadb", "pgvector", "qdrant", "pinecone", "weaviate"),
    "semantic search": ("embeddings", "vector search", "semantic retrieval"),
    "platform product": ("platform", "api-first", "microservices", "internal products"),
    "developer tools": ("internal tooling", "sdk", "api", "developer experience"),
    "systems thinking": ("solution architecture", "system design", "architecture"),
    "stakeholder management": ("stakeholder collaboration", "cross-functional", "stakeholder"),
    "success metrics": ("kpis", "okrs", "success criteria", "metrics"),
    "prioritization": ("prioritisation", "roadmap", "backlog"),
    "prioritisation": ("prioritization", "roadmap", "backlog"),
    "data modelling": ("data modeling", "ontology", "schema", "knowledge modelling"),
    "data modeling": ("data modelling", "ontology", "schema", "knowledge modelling"),
    "gcp": ("google cloud", "vertex ai", "bigquery", "pub/sub"),
    "google cloud": ("gcp", "vertex ai", "bigquery", "pub/sub"),
    "cloud": ("azure", "aws", "gcp", "google cloud", "cloud-native"),
    "process mapping": ("business analysis", "process improvement", "workflow"),
    "product requirements": ("prd", "brd", "user stories", "requirements definition"),
    "product management": ("product manager", "product owner", "product management"),
    "product strategy": ("product vision", "product roadmap", "roadmap"),
}

_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?years?", re.I)
_DEGREE = re.compile(
    r"\b(bachelor|master|msc|bsc|ba|bs|ms|mba|phd|degree in|computer science|engineering)\b",
    re.I,
)


@dataclass(frozen=True)
class Requirement:
    """One thing the posting asks for."""

    term: str
    tier: Tier
    #: The posting line it came from, kept so the UI can show why it was extracted.
    source: str = ""


@dataclass
class JobSpec:
    """Everything the tailoring engine needs to know about a posting."""

    title: str = ""
    requirements: list[Requirement] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    years_required: int | None = None
    degree_required: bool = False
    raw_text: str = ""

    def terms(self, *tiers: Tier) -> list[str]:
        wanted = set(tiers) or set(Tier)
        seen: dict[str, None] = {}
        for req in self.requirements:
            if req.tier in wanted:
                seen.setdefault(req.term, None)
        return list(seen)


def _tier_for_line(line: str, current: Tier) -> Tier:
    """Which block a line belongs to, tracking the most recent heading."""
    low = line.strip().lower().rstrip(":")
    if any(cue in low for cue in _PREFERRED_CUES) and len(low) < 70:
        return Tier.PREFERRED
    if any(cue in low for cue in _MANDATORY_CUES) and len(low) < 70:
        return Tier.MANDATORY
    if any(cue in low for cue in _RESPONSIBILITY_CUES) and len(low) < 70:
        return Tier.CONTEXTUAL
    return current


def _terms_in(text: str) -> list[str]:
    """Lexicon terms present in a stretch of text, longest first.

    Longest-first prevents "ml" claiming a hit inside "mlops" and double-counting the same
    evidence under two names.
    """
    low = f" {text.lower()} "
    found: list[str] = []
    for term in sorted(_LEXICON, key=len, reverse=True):
        pattern = re.escape(term)
        matched = re.search(rf"(?<![\w/]){pattern}(?![\w/])", low)
        # Longest-first ordering means a shorter term already covered by a longer one is a
        # duplicate view of the same evidence, not a second match.
        subsumed = any(term in already and term != already for already in found)
        if matched and not subsumed:
            found.append(term)
    return found


def parse_job(text: str, *, title: str = "") -> JobSpec:
    """Extract classified requirements from a posting."""
    spec = JobSpec(title=title.strip(), raw_text=text or "")
    current = Tier.CONTEXTUAL
    seen: set[tuple[str, Tier]] = set()

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        current = _tier_for_line(line, current)
        if current is Tier.CONTEXTUAL and len(line) > 40:
            spec.responsibilities.append(line)

        for term in _terms_in(line):
            key = (term, current)
            if key in seen:
                continue
            seen.add(key)
            spec.requirements.append(Requirement(term=term, tier=current, source=line[:200]))

        if spec.years_required is None and current is Tier.MANDATORY:
            match = _YEARS.search(line)
            if match:
                spec.years_required = int(match.group(1))
        if (
            not spec.degree_required
            and current is Tier.MANDATORY
            and _DEGREE.search(line)
        ):
            spec.degree_required = True

    # A term appearing in both blocks is mandatory; keep the strongest claim only.
    strongest: dict[str, Requirement] = {}
    rank = {Tier.MANDATORY: 3, Tier.PREFERRED: 2, Tier.CONTEXTUAL: 1}
    for req in spec.requirements:
        held = strongest.get(req.term)
        if held is None or rank[req.tier] > rank[held.tier]:
            strongest[req.term] = req
    spec.requirements = list(strongest.values())
    return spec


def lexicon() -> tuple[str, ...]:
    """Every skill term the extractor knows about."""
    return _LEXICON


def implications() -> dict[str, tuple[str, ...]]:
    """The full equivalence table: term -> wordings that evidence it."""
    return dict(_IMPLIES)


def equivalents(term: str) -> tuple[str, ...]:
    """Wordings that legitimately evidence ``term``."""
    return _IMPLIES.get(term.lower(), ())
