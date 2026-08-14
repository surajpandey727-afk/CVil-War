"""What is actually known about an employer, assembled from stored data only.

Written after auditing all ten job adapters against their live endpoints. The conclusion was
uncomfortable and is what shapes this module: **for most employers, almost nothing is known**.

* ``Job.company`` is the only company field persisted anywhere.
* No free source in this stack carries headcount, headquarters or company type. Not one.
* Two of ten adapters carry an industry (SmartRecruiters, Jobicy). The rest carry none, and
  Adzuna's ``category`` is the *job's* category — presenting it as the company's industry
  would be a correctness error, not a cosmetic one.
* No stored URL is a company website. Every one is a board or ATS host.

Two things are genuinely obtainable at zero cost, and this module does exactly those:

1. **The official site**, for employers whose jobs came from their own career board. The
   registry already maps ``careers:<slug>`` to a real domain, so it is a dictionary lookup —
   no network, no key, no guess. Employers found through an aggregator get nothing, because
   guessing a domain from a company name produces confident dead links.
2. **Their other open roles**, from the local database. Free, exact, and often the most
   useful thing on the panel.

Everything else is reported as unavailable, by name. That is the honest answer and it is also
the actionable one: it tells the operator to go and look, rather than implying the system
checked and found nothing.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_discovery.source_registry import CAREER_PAGES
from app.models.job import Job
from app.schemas.company import CompanyJob, CompanyProfile

logger = structlog.get_logger(__name__)

#: ``careers:<slug>`` maps to a real, curated domain. Built once from the registry the Sources
#: screen already uses, so a company enabled there and a company profiled here cannot disagree.
#: Keyed on the slug, never the label: the registry says "Ocado" where the board says "Ocado
#: Group", and a name-based join breaks on exactly that.
_DOMAIN_BY_SLUG: dict[str, str] = {slug: domain for slug, _label, domain in CAREER_PAGES}

#: Fields no free source in this stack provides. Listed explicitly so the UI names them rather
#: than rendering silent gaps, and so adding a source that *does* provide one is a visible
#: change here.
UNAVAILABLE_WITHOUT_ENRICHMENT = (
    "Company size",
    "Headquarters",
    "Company type",
    "Funding",
    "Products and services",
)

#: How many sibling roles to return. The count is exact; the list is capped for the panel.
_MAX_OTHER_JOBS = 8


def website_for(job: Job) -> tuple[str | None, str]:
    """The employer's own site, and how it was established.

    Only for jobs discovered through that employer's career board, where the domain comes
    from the curated registry. Everything else returns ``None`` — a guessed domain is a
    confident dead link on a page the operator is using to decide whether to apply.
    """
    platform = job.platform or ""
    if not platform.startswith("careers:"):
        return None, ""
    slug = platform.removeprefix("careers:")
    domain = _DOMAIN_BY_SLUG.get(slug)
    if not domain:
        return None, ""
    return f"https://{domain}", "career-page registry"


def industry_for(job: Job) -> str | None:
    """The employer's industry, where the source actually published one.

    Read from the adapter's own metadata rather than inferred. A job category is not an
    industry and is deliberately not used here.
    """
    raw = job.skills_required if isinstance(job.skills_required, dict) else {}
    industry = raw.get("industry")
    return str(industry) if industry else None


async def other_jobs(db: AsyncSession, job: Job) -> tuple[list[CompanyJob], int]:
    """Other roles at the same employer already in the operator's list.

    Matched case-insensitively on the company name, which is unnormalised free text with no
    foreign key — the same shape the policy service already uses for its per-employer cap, so
    the two agree about what counts as the same employer. Tenant scoping is automatic.
    """
    company = (job.company or "").strip()
    if not company:
        return [], 0

    rows = (
        await db.execute(
            select(Job)
            .where(
                func.lower(Job.company) == company.casefold(),
                Job.id != job.id,
            )
            .order_by(Job.created_at.desc())
            .limit(_MAX_OTHER_JOBS)
        )
    ).scalars().all()

    total = (
        await db.execute(
            select(func.count(Job.id)).where(
                func.lower(Job.company) == company.casefold(), Job.id != job.id
            )
        )
    ).scalar() or 0

    return [
        CompanyJob(job_id=row.id, title=row.title, location=row.location or "", url=row.url or "")
        for row in rows
    ], int(total)


async def profile_for(db: AsyncSession, job: Job) -> CompanyProfile:
    """Assemble everything known about this job's employer."""
    website, website_source = website_for(job)
    industry = industry_for(job)
    siblings, total = await other_jobs(db, job)

    unavailable = list(UNAVAILABLE_WITHOUT_ENRICHMENT)
    if not website:
        unavailable.insert(0, "Website")
    if not industry:
        unavailable.insert(0, "Industry")

    available = bool(website or industry or total)
    profile = CompanyProfile(
        name=job.company or "Unknown employer",
        available=available,
        website=website,
        website_source=website_source,
        industry=industry,
        source=job.platform or "",
        other_jobs=siblings,
        other_jobs_count=total,
        unavailable_fields=unavailable,
        unavailable_reason=(
            "This job came from an aggregator, which publishes the employer's name and "
            "nothing else about them. Company details would need a paid enrichment service, "
            "which this deployment deliberately does not use."
            if not website
            else "Company details beyond the official site would need a paid enrichment "
                 "service, which this deployment deliberately does not use."
        ),
    )
    logger.info(
        "company.profile_built",
        company=profile.name,
        has_website=bool(website),
        other_jobs=total,
    )
    return profile
