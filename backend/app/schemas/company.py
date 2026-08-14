"""Wire format for the company profile shown on a job.

Shaped around an uncomfortable fact established by auditing every adapter against its live
endpoint: under the zero-cost constraint, most of what a company profile would ideally show
is **not obtainable**. No free source in this stack carries headcount, headquarters or
company type, and only two of ten adapters carry an industry.

So the schema makes absence first-class. ``available`` says whether anything beyond the name
is known, ``unavailable_fields`` names what could not be established, and every enrichment
field is optional. The alternative — omitting the fields and letting the UI render blanks —
produces a profile that looks thin rather than one that is honest about its limits.

The website is the one enrichment that is real and free, and only for employers whose jobs
came from their own career board. It is never guessed from the company name: a wrong outbound
link on a job page is worse than no link.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyJob(BaseModel):
    """Another role at the same employer, already in the operator's list."""

    job_id: str
    title: str
    location: str = ""
    url: str = ""


class CompanyProfile(BaseModel):
    """What is actually known about an employer."""

    name: str
    #: False when nothing beyond the name could be established.
    available: bool = False
    #: The employer's own site. Present only where the job came from their career board and
    #: the domain is in the curated registry — never inferred from the name.
    website: str | None = None
    #: How the website was established, so a stale entry is attributable.
    website_source: str = ""
    #: Only from sources that publish it (SmartRecruiters, Jobicy). Absent otherwise.
    industry: str | None = None
    #: Present only where the source publishes a company blurb.
    description: str | None = None
    #: The board this employer's jobs came from.
    source: str = ""

    #: Other roles at this employer already discovered. An empty list is a real answer and
    #: the common one — most employers in a personal job cache have exactly one posting.
    other_jobs: list[CompanyJob] = Field(default_factory=list)
    other_jobs_count: int = 0

    #: Named so the UI can say precisely what is not known rather than showing gaps.
    #: e.g. ["Company size", "Headquarters", "Company type"].
    unavailable_fields: list[str] = Field(default_factory=list)
    #: Plain-English explanation shown once, rather than repeated per empty field.
    unavailable_reason: str = ""
