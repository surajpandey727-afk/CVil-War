"""The skill vocabulary the Skill Radar reasons over.

Two things live here and nothing else: a registry of skills (each with the surface forms a
résumé might spell it, so matching catches "experimentation" as well as "A/B testing"), and the
category each belongs to for grouping in the UI.

The point of a curated registry rather than "just count words in the job corpus" is that the
corpus is often empty - a brand-new account, or (right now) a discovery worker that has not run.
The Radar must still tell the candidate what a role wants. When the corpus *does* hold jobs, the
aggregator blends real posting frequency on top of these weights (see ``aggregate.py``); the
curation is the floor, not the ceiling.

Everything is domain knowledge about how these roles are actually hired and screened - stable,
well-established territory, not invented facts about any person.
"""



from __future__ import annotations

from dataclasses import dataclass, field


class Category:
    """Display groupings. Deliberately few - a candidate scans categories, not a flat list."""

    PRODUCT = "Product craft"
    AIML = "AI / ML"
    DATA = "Data & analytics"
    TECHNICAL = "Technical"
    LEADERSHIP = "Leadership & delivery"
    DOMAIN = "Domain & business"
    TOOLS = "Tools & platforms"

    ORDER = (PRODUCT, AIML, DATA, TECHNICAL, LEADERSHIP, DOMAIN, TOOLS)


@dataclass(frozen=True)
class Skill:
    """One screenable competency.

    ``aliases`` are the extra surface forms matched in a résumé beyond ``label`` itself. They are
    matched case-insensitively on word boundaries, so "sql" will not fire inside "mysql" and
    "roadmap" fires for "roadmapping". Keep them specific: a loose alias (e.g. "data") turns the
    coverage score into noise.
    """

    key: str
    label: str
    category: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    #: An ATS keyword is a term applicant-tracking filters screen on literally. Surfaced with a
    #: badge so the candidate knows which terms to mirror verbatim rather than paraphrase.
    ats: bool = False

    def surface_forms(self) -> tuple[str, ...]:
        """Every string that counts as this skill being present."""
        return (self.label.lower(), *(a.lower() for a in self.aliases))


def _s(key: str, label: str, category: str, *aliases: str, ats: bool = False) -> tuple[str, Skill]:
    return key, Skill(key=key, label=label, category=category, aliases=tuple(aliases), ats=ats)


# -- The registry ---------------------------------------------------------------------------
# Keyed by a stable slug. Labels are what the UI shows; aliases are what a résumé might say.
SKILLS: dict[str, Skill] = dict(
    (
        # Product craft
        _s(
            "roadmap",
            "Product roadmapping",
            Category.PRODUCT,
            "roadmap",
            "roadmapping",
            "product roadmap",
            ats=True,
        ),
        _s(
            "discovery",
            "Product discovery",
            Category.PRODUCT,
            "user research",
            "customer discovery",
            "continuous discovery",
        ),
        _s(
            "prioritization",
            "Prioritisation frameworks",
            Category.PRODUCT,
            "rice",
            "moscow",
            "prioritisation",
            "prioritization",
            "backlog prioritisation",
        ),
        _s(
            "prd",
            "PRDs & specs",
            Category.PRODUCT,
            "prd",
            "product requirements",
            "product spec",
            "specs",
            ats=True,
        ),
        _s(
            "lifecycle",
            "Product lifecycle",
            Category.PRODUCT,
            "product lifecycle",
            "0-to-1",
            "zero to one",
            "launch",
        ),
        _s(
            "gtm",
            "Go-to-market",
            Category.PRODUCT,
            "gtm",
            "go to market",
            "product launch",
            ats=True,
        ),
        _s(
            "metrics",
            "Product metrics & KPIs",
            Category.PRODUCT,
            "kpi",
            "kpis",
            "north star",
            "success metrics",
            "okrs",
            "okr",
            ats=True,
        ),
        _s(
            "agile",
            "Agile / Scrum",
            Category.PRODUCT,
            "agile",
            "scrum",
            "kanban",
            "sprint",
            "sprints",
            ats=True,
        ),
        _s(
            "userstory",
            "User stories",
            Category.PRODUCT,
            "user stories",
            "acceptance criteria",
            "epics",
        ),
        _s(
            "ux",
            "UX collaboration",
            Category.PRODUCT,
            "ux",
            "user experience",
            "wireframes",
            "figma",
            "prototyping",
        ),
        # AI / ML
        _s(
            "genai",
            "Generative AI / LLMs",
            Category.AIML,
            "genai",
            "llm",
            "llms",
            "large language model",
            "gpt",
            ats=True,
        ),
        _s(
            "rag",
            "RAG & retrieval",
            Category.AIML,
            "rag",
            "retrieval augmented",
            "vector search",
            "embeddings",
        ),
        _s(
            "prompteng",
            "Prompt engineering",
            Category.AIML,
            "prompt engineering",
            "prompting",
            "prompt design",
        ),
        _s(
            "mlops",
            "MLOps",
            Category.AIML,
            "mlops",
            "model deployment",
            "model monitoring",
            "ml pipeline",
            ats=True,
        ),
        _s(
            "ml",
            "Machine learning",
            Category.AIML,
            "machine learning",
            "ml models",
            "supervised learning",
            ats=True,
        ),
        _s(
            "nlp", "NLP", Category.AIML, "nlp", "natural language processing", "text classification"
        ),
        _s(
            "cv",
            "Computer vision",
            Category.AIML,
            "computer vision",
            "opencv",
            "yolo",
            "image recognition",
        ),
        _s(
            "aieval",
            "Model evaluation",
            Category.AIML,
            "model evaluation",
            "eval",
            "evals",
            "benchmarking",
            "offline evaluation",
        ),
        _s(
            "aigov",
            "AI governance",
            Category.AIML,
            "ai governance",
            "responsible ai",
            "model risk",
            "guardrails",
        ),
        _s("agents", "AI agents", Category.AIML, "agents", "agentic", "tool use", "orchestration"),
        # Data & analytics
        _s("sql", "SQL", Category.DATA, "sql", ats=True),
        _s(
            "experimentation",
            "Experimentation / A/B",
            Category.DATA,
            "a/b testing",
            "ab testing",
            "experimentation",
            "split test",
            "hypothesis testing",
            ats=True,
        ),
        _s(
            "analytics",
            "Product analytics",
            Category.DATA,
            "product analytics",
            "amplitude",
            "mixpanel",
            "funnel analysis",
        ),
        _s(
            "dataviz",
            "Data visualisation",
            Category.DATA,
            "data visualization",
            "data visualisation",
            "tableau",
            "power bi",
            "looker",
            "dashboards",
        ),
        _s(
            "stats",
            "Statistics",
            Category.DATA,
            "statistics",
            "statistical",
            "regression",
            "significance",
        ),
        _s(
            "datamodel",
            "Data modelling",
            Category.DATA,
            "data modeling",
            "data modelling",
            "dbt",
            "star schema",
        ),
        _s(
            "etl",
            "ETL / pipelines",
            Category.DATA,
            "etl",
            "elt",
            "data pipeline",
            "airflow",
            "data ingestion",
        ),
        _s("cohort", "Cohort & retention", Category.DATA, "cohort", "retention", "churn", "ltv"),
        # Technical
        _s("python", "Python", Category.TECHNICAL, "python", ats=True),
        _s(
            "apis",
            "APIs",
            Category.TECHNICAL,
            "api",
            "apis",
            "rest",
            "graphql",
            "webhooks",
            ats=True,
        ),
        _s(
            "cloud",
            "Cloud (AWS/Azure/GCP)",
            Category.TECHNICAL,
            "aws",
            "azure",
            "gcp",
            "cloud",
            ats=True,
        ),
        _s(
            "sysdesign",
            "System design",
            Category.TECHNICAL,
            "system design",
            "architecture",
            "distributed systems",
            "scalability",
        ),
        _s(
            "cicd",
            "CI/CD",
            Category.TECHNICAL,
            "ci/cd",
            "cicd",
            "continuous integration",
            "github actions",
        ),
        _s(
            "docker",
            "Containers / K8s",
            Category.TECHNICAL,
            "docker",
            "kubernetes",
            "k8s",
            "containers",
        ),
        _s(
            "datapipe",
            "Spark / big data",
            Category.TECHNICAL,
            "spark",
            "pyspark",
            "hadoop",
            "big data",
        ),
        # Leadership & delivery
        _s(
            "stakeholder",
            "Stakeholder management",
            Category.LEADERSHIP,
            "stakeholder",
            "stakeholders",
            "stakeholder management",
            ats=True,
        ),
        _s(
            "crossfunc",
            "Cross-functional leadership",
            Category.LEADERSHIP,
            "cross-functional",
            "cross functional",
            "xfn",
            ats=True,
        ),
        _s(
            "strategy",
            "Strategy",
            Category.LEADERSHIP,
            "strategy",
            "strategic",
            "product strategy",
            "vision",
            ats=True,
        ),
        _s(
            "comms",
            "Communication",
            Category.LEADERSHIP,
            "communication",
            "presenting",
            "storytelling",
            "influence",
        ),
        _s(
            "mentoring",
            "Mentoring / people",
            Category.LEADERSHIP,
            "mentoring",
            "coaching",
            "line management",
            "people management",
        ),
        _s(
            "delivery",
            "Delivery / execution",
            Category.LEADERSHIP,
            "delivery",
            "execution",
            "shipping",
            "end-to-end ownership",
        ),
        # Domain & business
        _s("b2b", "B2B / SaaS", Category.DOMAIN, "b2b", "saas", "enterprise", "b2c"),
        _s(
            "fintech",
            "Fintech / payments",
            Category.DOMAIN,
            "fintech",
            "payments",
            "banking",
            "regtech",
        ),
        _s(
            "growth",
            "Growth",
            Category.DOMAIN,
            "growth",
            "acquisition",
            "activation",
            "monetisation",
            "monetization",
        ),
        _s(
            "pnl",
            "Commercial / P&L",
            Category.DOMAIN,
            "p&l",
            "revenue",
            "business case",
            "roi",
            "pricing",
        ),
        _s(
            "compliance",
            "Compliance / GDPR",
            Category.DOMAIN,
            "gdpr",
            "compliance",
            "regulatory",
            "data privacy",
        ),
        # Tools & platforms
        _s("jira", "Jira", Category.TOOLS, "jira", "confluence"),
        _s("git", "Git", Category.TOOLS, "git", "github", "gitlab", "version control"),
        _s("notebooks", "Notebooks", Category.TOOLS, "jupyter", "notebook", "pandas", "numpy"),
        _s(
            "pytorch",
            "PyTorch / TensorFlow",
            Category.TOOLS,
            "pytorch",
            "tensorflow",
            "keras",
            "scikit-learn",
            "sklearn",
        ),
        _s(
            "langchain",
            "LangChain / LlamaIndex",
            Category.TOOLS,
            "langchain",
            "llamaindex",
            "langgraph",
        ),
    )
)


def get_skill(key: str) -> Skill | None:
    return SKILLS.get(key)
