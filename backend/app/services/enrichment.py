"""Fetch the full posting for a job and keep what it says.

Search results are summaries. A LinkedIn card carries a title, a company and a location and
nothing else — which is why every fit analysis on a LinkedIn role came back "0 strong matches,
0 to address", with required skills, location and salary all marked *not assessed*. There was
genuinely nothing to assess: the description column was empty for all thirty-four of them.

This closes that gap on demand rather than during discovery. A sweep pulling a hundred
descriptions would be rate-limited long before it finished; a job the operator has opened is
one request for something they are about to read.

What gets stored is the posting's own words. Requirement lines are lifted verbatim rather than
paraphrased, and the employer's criteria labels are kept as the employer wrote them — a stored
record that disagrees with the page it came from is worse than no record at all.
"""
# ruff: noqa: RUF001, RUF003
# The "ambiguous unicode" rule fires on every curly quote, en dash and bullet below. Those
# characters are the subject of this module, not a typo in it: real postings are written with
# them, and the extractor's job is to recognise them. Replacing them with ASCII look-alikes
# would break the very matching this file exists to do.

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.automation.platforms.registry import platform_registry
from app.core.job_discovery.sources.base import SourceUnavailableError
from app.models.job import Job

logger = structlog.get_logger(__name__)

#: Headings that open a requirements list.
_REQUIREMENT_HEADINGS = re.compile(
    r"\b("
    r"requirements?|qualifications?|essential|must[- ]haves?|nice[- ]to[- ]haves?"
    r"|what we(?:'re| are)? looking for|what you(?:'ll| will)? (?:need|bring|have)"
    r"|who (?:you are|we(?:'re| are)? looking for)|about you|your (?:profile|experience|background)"
    r"|skills? (?:and|&) experience|experience (?:required|we(?:'re| are)? looking for)"
    r"|you (?:should )?(?:have|thrive|are)|ideal candidate|you might be a (?:great )?fit"
    r")\b",
    re.I,
)
#: Headings that open a benefits list.
_BENEFIT_HEADINGS = re.compile(
    r"\b(benefits?|what we offer|perks?|why join|our offer|package|we offer"
    r"|what you(?:'ll| will)? get|compensation (?:and|&) benefits)\b",
    re.I,
)
#: Headings that *close* the section they follow. Without these, everything after a
#: requirements list — the company blurb, the interview process — keeps being collected as a
#: requirement, which is how a posting ends up "asking for" its own equal-opportunity notice.
_SECTION_END = re.compile(
    r"\b(about (?:us|the (?:company|team|role))|how we hire|our (?:mission|values|process)"
    r"|the (?:department|role|opportunity)|interview process|next steps|equal opportunit"
    r"|what you(?:'ll| will)? do|responsibilit|apply now|to apply)\b",
    re.I,
)
#: A bullet as it survives HTML-to-text, for sources that publish prose rather than lists.
_BULLET = re.compile(r"(?:^|\s)[•▪◦‣·*\-–—]\s+|(?:^|\s)\d{1,2}[.)]\s+")
#: Years-of-experience claims — the single most load-bearing requirement in any posting.
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?years?\b", re.I)

#: Curly punctuation, which postings use constantly and which defeats any pattern written with
#: typewriter characters. "What We’re Looking For" matched nothing until this was normalised,
#: and the failure was invisible: the job reported no requirements, exactly as a posting
#: genuinely without a requirements section would.
_SMART = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-"})

#: Lines shorter than this are headings or fragments; longer are paragraphs. Both make poor
#: requirement lines.
_MIN_LINE, _MAX_LINE = 12, 320
#: A heading is short. A line long enough to carry content is treated as content even when it
#: happens to contain a heading phrase.
_HEADING_MAX = 60


def normalise(text: str) -> str:
    """Fold typographic punctuation so ASCII patterns still match."""
    return text.translate(_SMART)


def _lines(text: str) -> list[str]:
    """Split a posting into candidate lines, preferring the structure it was written with.

    Newlines first: the HTML-to-text step preserves list items as their own lines, and that is
    a far better signal than any punctuation heuristic. Bullets and sentence boundaries remain
    as fallbacks for sources that publish one continuous run of prose.
    """
    lines = [ln.strip(" \t-–—•*‣▪") for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    if len(lines) > 3:
        return lines

    parts = [p.strip(" \t-–—•*") for p in _BULLET.split(text) if p and p.strip()]
    if len(parts) > 1:
        return [p for p in parts if len(p) > _MIN_LINE]
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if len(s.strip()) > 25]


def extract_sections(description: str) -> dict[str, list[str]]:
    """Pull requirement and benefit lines out of a posting body, verbatim.

    Deliberately not a model call. This runs whenever the operator opens a job, must work when
    the gateway is unreachable, and the task is locating text the posting already contains — a
    model would add latency and a chance of inventing a requirement that is not there.
    """
    if not description.strip():
        return {"requirements": [], "benefits": []}

    requirements: list[str] = []
    benefits: list[str] = []
    #: Which list the current run of lines belongs to, set by the last heading seen.
    bucket: str | None = None

    for line in _lines(normalise(description)):
        head = line[:90]
        is_heading = len(line) < _HEADING_MAX

        if _REQUIREMENT_HEADINGS.search(head):
            bucket = "requirements"
            if is_heading:
                continue  # a bare heading carries no requirement of its own
        elif _BENEFIT_HEADINGS.search(head):
            bucket = "benefits"
            if is_heading:
                continue
        elif is_heading and _SECTION_END.search(head):
            bucket = None
            continue

        if not (_MIN_LINE < len(line) < _MAX_LINE):
            continue

        # A line naming a concrete year count is a requirement wherever it appears: postings
        # routinely state the hard experience bar outside any labelled section.
        if _YEARS.search(line):
            if line not in requirements:
                requirements.append(line)
            continue

        if bucket == "requirements" and line not in requirements:
            requirements.append(line)
        elif bucket == "benefits" and line not in benefits:
            benefits.append(line)

    return {"requirements": requirements[:30], "benefits": benefits[:20]}


def years_required(requirements: list[str]) -> int | None:
    """The largest explicit year count the posting asks for, or None if it never says.

    The maximum rather than the first: a posting wanting "3+ years product and 5+ years in a
    regulated domain" is a five-year posting, and reporting three would understate the bar.
    """
    counts = [
        int(match) for line in requirements for match in _YEARS.findall(line) if match.isdigit()
    ]
    return max(counts) if counts else None


def summarise(job: Job, sections: dict[str, list[str]], criteria: dict[str, str]) -> dict:
    """The at-a-glance facts a dashboard tile can show without re-reading the posting."""
    return {
        "criteria": criteria,
        "requirements": sections["requirements"],
        "benefits": sections["benefits"],
        "years_required": years_required(sections["requirements"]),
        "word_count": len((job.description or "").split()),
        "requirement_count": len(sections["requirements"]),
        "benefit_count": len(sections["benefits"]),
        "source": job.platform,
    }


async def enrich_job(db: AsyncSession, job: Job, *, force: bool = False) -> Job:
    """Fetch the full posting for ``job`` and persist what it says.

    Returns the job either way. A source that cannot serve details is not an error the caller
    must handle — the job keeps the summary it already had and ``enriched_at`` stays ``None``,
    so the screen can say "not fetched yet" rather than the much worse "no requirements".
    """
    if job.enriched_at and not force:
        return job

    detail: dict[str, Any] | None = None
    try:
        if platform_registry.has(job.platform):
            adapter = platform_registry.create(job.platform)
            if hasattr(adapter, "fetch_detail"):
                detail = await adapter.fetch_detail(job.platform_job_id)
            elif hasattr(adapter, "fetch_description"):
                text = await adapter.fetch_description(job.platform_job_id)
                detail = {"description": text or "", "criteria": {}}
    except SourceUnavailableError as exc:
        # A rate limit is "come back later", not a fact about the job.
        logger.info("enrich_unavailable", job_id=job.id, platform=job.platform, reason=str(exc))
        return job
    except Exception as exc:
        logger.warning("enrich_failed", job_id=job.id, platform=job.platform, error=str(exc))
        return job

    if detail is not None:
        description = (detail.get("description") or "").strip()
        if description and len(description) > len(job.description or ""):
            job.description = description
        criteria = detail.get("criteria") or {}
    elif (job.description or "").strip():
        # No adapter can serve details, but there is already a body to read.
        criteria = {}
    else:
        return job

    sections = extract_sections(job.description or "")
    job.posting_data = summarise(job, sections, criteria)

    # LinkedIn states employment type and seniority explicitly. Use them rather than guessing
    # from the title, but never overwrite what the search already established.
    if not job.job_type and criteria.get("Employment type"):
        job.job_type = criteria["Employment type"][:50]
    if not job.experience_level and criteria.get("Seniority level"):
        level = criteria["Seniority level"]
        if level.lower() not in {"not applicable", "n/a", ""}:
            job.experience_level = level[:50]

    job.enriched_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    logger.info(
        "job_enriched", job_id=job.id, platform=job.platform,
        description_chars=len(job.description or ""),
        requirements=len(sections["requirements"]),
    )
    return job
