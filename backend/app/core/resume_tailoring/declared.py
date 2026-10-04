"""The experience the owner has declared in the standing brief, as evidence the tailoring can use.

The standing résumé brief says, in the owner's words, that a CV is a curated selection and not an
inventory: over the last three years they worked across data, analytics, AI, engineering, product
and BI, and finance-related technology is the one area they did not work in. The planner and the
validators are told this through the brief; this module hands the same declaration to the code, so
that "the CV does not mention it" stops being an automatic reason to refuse a term.

What it permits is narrow and checkable:

* a capability named here may be written into a bullet, a summary or a skills row where that line's
  work genuinely involves it. The change log names this source for every term recovered from it;
* nothing here supplies an employer, a project, a credential, a date or a figure — those still have
  to come from the CV or the career profile, and the validators still reject invented ones;
* the declaration is open-ended, as the brief's is ("including, but not limited to", "almost
  everything excluding finance"): any skill, tool, methodology, domain or behavioural requirement of
  the posting being tailored for counts as declared unless it is in an excluded domain. Duties, years,
  degrees, certifications and clearances are not skills and are never declared;
* the excluded domains below are never written, whatever a posting asks for.
"""

from __future__ import annotations

import re

from app.core.resume_tailoring.trusted import TrustedSource

LABEL = "Owner-declared experience (standing brief)"

#: Capability areas from the brief, one term per entry. Wording is the brief's own.
CAPABILITIES: dict[str, tuple[str, ...]] = {
    "Data & Analytics": (
        "Data Science", "Machine Learning", "Statistical Modelling", "Predictive Analytics",
        "Deep Learning", "NLP", "Text Analytics", "Feature Engineering", "Data Pre-processing",
        "Exploratory Data Analysis", "EDA", "Forecasting", "Experimentation", "A/B Testing",
        "Customer Analytics", "Product Analytics", "Marketing Analytics", "Business Analytics",
        "Data Visualisation", "Data Visualization", "BI", "Business Intelligence", "Dashboarding",
        "Dashboards", "Reporting", "Data Storytelling", "Decision Support", "Commercial Analytics",
        "Operational Analytics", "Data Products",
    ),
    "Engineering & Data Infrastructure": (
        "Python", "SQL", "ETL", "ELT", "Data Pipelines", "APIs", "REST APIs",
        "Backend Development", "Service Development", "Database Systems", "Data Modelling",
        "Data Modeling", "Data Integration", "System Integration", "Docker", "Cloud Infrastructure",
        "AWS", "Productionisation", "Productionization", "Automation", "Monitoring", "Data Quality",
        "Data Governance",
    ),
    "AI": (
        "Generative AI", "AI-enabled Applications", "Recommendation Systems", "Predictive Systems",
        "AI Product Development", "AI Governance", "Model Evaluation", "Model Monitoring",
        "AI Workflow Automation",
    ),
    "Product & Technology": (
        "Product Management", "Technical Product Management", "Requirements Engineering", "PRDs",
        "BRDs", "Product Roadmaps", "Technical Roadmaps", "Solution Design", "System Design",
        "Integrations", "ERP Integrations", "Enterprise Integrations", "Technical Documentation",
        "Stakeholder Management", "Client-facing Technical Delivery", "Agile", "Scrum",
        "Sprint Planning", "Backlog Management", "Cross-functional Delivery",
    ),
    "Business Intelligence": ("Power BI", "Tableau", "BI Reporting", "Data Storytelling"),
}

#: Domains the owner said they did not work in. Never written, never recoverable.
EXCLUDED_DOMAIN_TERMS: tuple[str, ...] = (
    "finance", "financial", "fintech", "banking", "payments", "payment gateway", "trading",
    "treasury", "ledger", "general ledger", "accounting", "credit risk", "underwriting",
    "regtech", "aml", "kyc", "capital markets", "wealth management", "core banking",
)


#: Requirement types that name a capability (as opposed to a duty, a degree, a certification, a
#: number of years or a place).
_CAPABILITY_TYPES = frozenset(
    ("TECHNOLOGY", "SKILL", "DOMAIN", "TOOL", "METHODOLOGY", "BEHAVIOUR", "INDUSTRY")
)

_EXCLUDED = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    + "|".join(re.escape(t) for t in EXCLUDED_DOMAIN_TERMS)
    + r")(?![A-Za-z0-9])",
    re.I,
)


def declared_text(job_terms: tuple[str, ...] = ()) -> str:
    lines = ["The owner states they worked with, or on, each of these in the last three years:"]
    lines += [f"{area}: {', '.join(terms)}" for area, terms in CAPABILITIES.items()]
    if job_terms:
        lines.append(
            "And, for the posting being tailored for, these skills, tools, methods and domains it "
            "asks for: " + ", ".join(job_terms)
        )
    return "\n".join(lines)


def posting_capabilities(job_text: str, title: str = "") -> tuple[str, ...]:
    """The skills a posting asks for that the owner's declaration covers: all but finance."""
    if not job_text.strip():
        return ()
    from app.core.ats_engine.requirements import requirements_for

    wanted = requirements_for(job_text, title)
    seen: dict[str, None] = {}
    for item in wanted.items:
        if item.type.value in _CAPABILITY_TYPES and not _EXCLUDED.search(item.term):
            seen.setdefault(item.term, None)
    return tuple(seen)


def declared_source(job_text: str = "", title: str = "") -> TrustedSource:
    """The declaration as a trusted source, labelled so the change log can cite it."""
    return TrustedSource(LABEL, declared_text(posting_capabilities(job_text, title)))


def with_declared(
    trusted: tuple[TrustedSource, ...] | list[TrustedSource],
    job_text: str = "",
    title: str = "",
) -> tuple[TrustedSource, ...]:
    """``trusted`` plus the declaration (covering this posting's skills), once."""
    if any(t.label == LABEL for t in trusted):
        return tuple(trusted)
    return (*trusted, declared_source(job_text, title))


def excluded_terms_added(before: str, after: str) -> list[str]:
    """Finance-domain words an edit introduces that the original line did not contain."""
    old = {m.group(0).lower() for m in _EXCLUDED.finditer(before)}
    return sorted({m.group(0).lower() for m in _EXCLUDED.finditer(after)} - old)
