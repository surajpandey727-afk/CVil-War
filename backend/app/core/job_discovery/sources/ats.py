"""Employer ATS board adapters — the zero-cost route to company career pages.

Greenhouse, Lever, Ashby and SmartRecruiters each publish the vacancies of any company using
them through a **public, keyless, officially documented** endpoint. That makes them the single
highest-coverage free source available: one HTTP call returns an employer's entire live board,
already structured, with no scraping, no key, no quota negotiation and no terms-of-service
grey area.

Measured against the live endpoints while writing this:

===============  ======  ==========================================
Board            Jobs    Endpoint
===============  ======  ==========================================
Anthropic         413    boards-api.greenhouse.io/v1/boards/<token>
Palantir          309    api.lever.co/v0/postings/<token>
Ramp              135    api.ashbyhq.com/posting-api/job-board/<token>
Monzo              80    boards-api.greenhouse.io/v1/boards/<token>
===============  ======  ==========================================

Each employer is registered as its own source under the ``careers:<slug>`` key already used by
``core/job_discovery/source_registry``, so the operator can switch individual companies on and
off, and a job's ``platform`` records which employer it came from.

**Discovery only.** These endpoints publish vacancies; they do not accept submissions. Every
listing therefore carries the employer's own apply URL (``get_application_url``), and applying
happens there. That separation is deliberate — see the brief's §10.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from app.core.automation.platforms.base import JobListing
from app.core.job_discovery.sources.base import (
    REQUEST_TIMEOUT_S,
    USER_AGENT,
    ApiJobSource,
    CostType,
    strip_html,
)


def _iso_from_epoch_ms(value: Any) -> str:
    """Lever publishes ``createdAt`` as epoch milliseconds."""
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError):
        return ""


class AtsBoardSource(ApiJobSource):
    """One employer's board on a hosted ATS.

    Subclasses supply the URL template and the record mapping; the employer is injected as
    ``board_token`` so a single class serves every company on that ATS.
    """

    #: ``{token}`` is substituted with :attr:`board_token`.
    endpoint_template: ClassVar[str] = ""
    #: Human-readable employer name, used as ``JobListing.company``.
    company_name: str = ""
    #: The employer's identifier on this ATS.
    board_token: str = ""

    cost_type = CostType.FREE

    def capabilities(self) -> dict[str, bool]:
        caps = super().capabilities()
        caps["application_url"] = True
        return caps

    def _url(self) -> str:
        return self.endpoint_template.format(token=self.board_token)

    async def _fetch(
        self, client: httpx.AsyncClient, query: str, location: str, limit: int
    ) -> list[dict[str, Any]]:
        # These endpoints return the whole board in one response and take no search
        # parameters, so filtering is entirely local (handled by the base class).
        response = await client.get(self._url())
        response.raise_for_status()
        return self._records(response.json())

    def _records(self, payload: Any) -> list[dict[str, Any]]:
        """Pull the job array out of this ATS's envelope."""
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict):
            for key in ("jobs", "content", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [r for r in value if isinstance(r, dict)]
        return []


class GreenhouseSource(AtsBoardSource):
    """Greenhouse job board. ``?content=true`` includes the HTML description."""

    endpoint_template = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        location = record.get("location") or {}
        where = location.get("name", "") if isinstance(location, dict) else str(location)
        return JobListing(
            platform=self.source_name,
            platform_job_id=str(record.get("id") or ""),
            title=(record.get("title") or "").strip(),
            company=self.company_name or (record.get("company_name") or "").strip(),
            location=where,
            url=record.get("absolute_url") or "",
            # Greenhouse double-escapes the description (&lt;p&gt;), so unescape before the
            # tag strip or the output keeps literal "&lt;div&gt;" noise.
            description=strip_html(_unescape(record.get("content") or "")),
            remote="remote" in where.lower(),
            posted_at=str(record.get("first_published") or record.get("updated_at") or ""),
            raw_data={"departments": [d.get("name") for d in record.get("departments") or []]},
        )


class LeverSource(AtsBoardSource):
    """Lever postings feed."""

    endpoint_template = "https://api.lever.co/v0/postings/{token}?mode=json"

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        categories = record.get("categories") or {}
        where = categories.get("location", "") if isinstance(categories, dict) else ""
        workplace = (record.get("workplaceType") or "").lower()
        return JobListing(
            platform=self.source_name,
            platform_job_id=str(record.get("id") or ""),
            title=(record.get("text") or "").strip(),
            company=self.company_name,
            location=where,
            # hostedUrl is the public posting; applyUrl jumps straight into the form.
            url=record.get("hostedUrl") or record.get("applyUrl") or "",
            description=(record.get("descriptionPlain") or "")[:20000],
            job_type=str(categories.get("commitment", "")) if isinstance(categories, dict) else "",
            remote=workplace == "remote" or "remote" in where.lower(),
            posted_at=_iso_from_epoch_ms(record.get("createdAt")),
            raw_data={
                "team": categories.get("team") if isinstance(categories, dict) else None,
                # Lever's own apply link. Previously read back out of raw_data by
                # `get_application_url` but never written into it, so the fallback was dead
                # code and the apply URL was always just the posting URL.
                "apply_url": record.get("applyUrl") or None,
            },
        )

    def get_application_url(self, listing: JobListing) -> str:
        return (listing.raw_data or {}).get("apply_url") or listing.url


class AshbySource(AtsBoardSource):
    """Ashby public job board."""

    endpoint_template = "https://api.ashbyhq.com/posting-api/job-board/{token}"

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        # isListed=False are drafts/internal postings that should not surface.
        if record.get("isListed") is False:
            return None
        return JobListing(
            platform=self.source_name,
            platform_job_id=str(record.get("id") or ""),
            title=(record.get("title") or "").strip(),
            company=self.company_name,
            location=record.get("location") or "",
            url=record.get("jobUrl") or record.get("applyUrl") or "",
            description=(record.get("descriptionPlain") or "")[:20000],
            job_type=str(record.get("employmentType") or ""),
            remote=bool(record.get("isRemote")),
            posted_at=str(record.get("publishedAt") or ""),
            raw_data={"team": record.get("team"), "department": record.get("department")},
        )


class SmartRecruitersSource(AtsBoardSource):
    """SmartRecruiters public postings API."""

    endpoint_template = "https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100"

    def _to_listing(self, record: dict[str, Any]) -> JobListing | None:
        loc = record.get("location") or {}
        where = ", ".join(
            str(loc.get(k)) for k in ("city", "country") if isinstance(loc, dict) and loc.get(k)
        )
        job_id = str(record.get("id") or "")
        industry = record.get("industry") or {}
        return JobListing(
            platform=self.source_name,
            platform_job_id=job_id,
            title=(record.get("name") or "").strip(),
            company=self.company_name,
            location=where,
            # `ref` is the API self-link (https://api.smartrecruiters.com/v1/...), which
            # returns raw JSON. It was being stored as the job URL, so "Open job" sent the
            # operator to a JSON document. The public posting page is the documented
            # jobs.smartrecruiters.com form; verified 200 and redirecting to the canonical
            # slug. Constructed from the board token and id, both of which came from the API.
            url=f"https://jobs.smartrecruiters.com/{self.board_token}/{job_id}",
            # The list endpoint carries no description at all — the previous read of
            # `jobAd` matched no key, so every SmartRecruiters job was stored with an empty
            # description and scored against nothing. The full text lives on the per-posting
            # detail endpoint; see `fetch_description`.
            description="",
            job_type=str(record.get("typeOfEmployment", {}).get("label") or ""),
            remote=bool(isinstance(loc, dict) and loc.get("remote")),
            posted_at=str(record.get("releasedDate") or ""),
            # Free metadata the list response already carries and the adapter was discarding.
            # `JobListing` has no seniority field, so experience level rides in raw_data with
            # the rest rather than being dropped.
            raw_data={
                "industry": industry.get("label") if isinstance(industry, dict) else None,
                "function": (record.get("function") or {}).get("label"),
                "department": (record.get("department") or {}).get("label"),
                "experience_level": (record.get("experienceLevel") or {}).get("label"),
            },
        )

    async def fetch_description(self, job_id: str) -> str:
        """Full posting text for one job, from the detail endpoint.

        Kept off the search path deliberately: the list endpoint returns no description, and
        fetching one per result would turn a single search call into one per job. This is
        called when a human opens the job, where one request is proportionate.
        """
        url = f"https://api.smartrecruiters.com/v1/companies/{self.board_token}/postings/{job_id}"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            response = await client.get(url, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            sections = (response.json().get("jobAd") or {}).get("sections") or {}
        parts = [
            (sections.get(key) or {}).get("text") or ""
            for key in ("jobDescription", "qualifications", "additionalInformation")
        ]
        return strip_html("\n\n".join(p for p in parts if p))


#: ``slug -> (adapter class, board token, display name)``.
#:
#: Slugs match the ``careers:<slug>`` keys already in ``source_registry.CAREER_PAGES``, so
#: switching a company on in the Sources screen enables exactly this adapter. Tokens were
#: resolved against the live endpoints; a company that has since moved ATS simply returns
#: nothing and is reported DEGRADED rather than breaking the run.
COMPANY_BOARDS: dict[str, tuple[type[AtsBoardSource], str, str]] = {
    # Every token below was resolved by probing the live endpoint; the count in the comment is
    # what it returned on 2026-08-13. Guessing a token silently yields a 404 and a permanently
    # empty source, so none of these are assumed.
    "anthropic": (GreenhouseSource, "anthropic", "Anthropic"),          # 413
    "palantir": (LeverSource, "palantir", "Palantir"),                  # 309
    "monzo": (GreenhouseSource, "monzo", "Monzo"),                      # 80
    "isomorphic": (GreenhouseSource, "isomorphiclabs", "Isomorphic Labs"),  # 23
    "wayve": (GreenhouseSource, "wayve", "Wayve"),                      # 103
    "lendable": (AshbySource, "lendable", "Lendable"),                  # 71
    "trainline": (AshbySource, "trainline", "Trainline"),               # 50
    "ocado": (GreenhouseSource, "ocadogroup", "Ocado Group"),           # 53
    # SmartRecruiters rather than Greenhouse: gh/wise returns a single stale US posting,
    # sr/Wise returns the real board.
    "wise": (SmartRecruitersSource, "Wise", "Wise"),                    # 420

    # Below: resolved the same way (live-probed, not guessed) on 2026-08-30, expanding
    # career-page coverage from 9 employers to 56 for AI/data/ML/PM-adjacent roles per the
    # operator's request for far broader company coverage than the original eight-ish list.
    "deepmind": (GreenhouseSource, "deepmind", "DeepMind"),             # 9
    "openai": (AshbySource, "openai", "OpenAI"),                        # 758
    "asos": (SmartRecruitersSource, "asos", "ASOS"),                    # 64
    "spotify": (LeverSource, "spotify", "Spotify"),                     # 89

    "quantexa": (AshbySource, "quantexa", "Quantexa"),                  # 30
    "synthesia": (AshbySource, "synthesia", "Synthesia"),               # 60
    "speechmatics": (GreenhouseSource, "speechmatics", "Speechmatics"), # 8
    "faculty": (AshbySource, "faculty", "Faculty AI"),                  # 73
    "tractable": (AshbySource, "tractable", "Tractable"),               # 5
    "graphcore": (GreenhouseSource, "graphcore", "Graphcore"),          # 194
    "improbable": (AshbySource, "improbable", "Improbable"),            # 7
    "gocardless": (GreenhouseSource, "gocardless", "GoCardless"),       # 25
    "zopa": (LeverSource, "zopa", "Zopa"),                              # 30
    "truelayer": (GreenhouseSource, "truelayer", "TrueLayer"),          # 5
    "clearbank": (AshbySource, "clearbank", "ClearBank"),               # 10
    "marshmallow": (AshbySource, "marshmallow", "Marshmallow"),         # 11
    "cleo": (GreenhouseSource, "cleo", "Cleo"),                         # 4
    "snowflake": (AshbySource, "snowflake", "Snowflake"),               # 389
    "databricks": (GreenhouseSource, "databricks", "Databricks"),       # 857
    "datadog": (GreenhouseSource, "datadog", "Datadog"),                # 454
    "fivetran": (GreenhouseSource, "fivetran", "Fivetran"),             # 237
    "similarweb": (GreenhouseSource, "similarweb", "Similarweb"),       # 68
    "contentsquare": (LeverSource, "contentsquare", "Contentsquare"),   # 28
    "alphasense": (GreenhouseSource, "alphasense", "AlphaSense"),       # 235
    "stripe": (GreenhouseSource, "stripe", "Stripe"),                   # 574
    "notion": (AshbySource, "notion", "Notion"),                        # 133
    "figma": (GreenhouseSource, "figma", "Figma"),                      # 163
    "canva": (SmartRecruitersSource, "canva", "Canva"),                 # 268
    "airtable": (GreenhouseSource, "airtable", "Airtable"),             # 16
    "asana": (GreenhouseSource, "asana", "Asana"),                      # 123
    "miro": (AshbySource, "miro", "Miro"),                              # 37
    "linear": (AshbySource, "linear", "Linear"),                        # 29
    "vercel": (GreenhouseSource, "vercel", "Vercel"),                   # 91
    "gitlab": (GreenhouseSource, "gitlab", "GitLab"),                   # 220
    "thoughtworks": (GreenhouseSource, "thoughtworks", "Thoughtworks"), # 51
    "cohere": (AshbySource, "cohere", "Cohere"),                        # 146
    "stabilityai": (GreenhouseSource, "stabilityai", "Stability AI"),   # 4
    "elevenlabs": (AshbySource, "elevenlabs", "ElevenLabs"),            # 248
    "runwayml": (AshbySource, "runway", "Runway"),                      # 4
    "perplexity": (AshbySource, "perplexity", "Perplexity"),            # 97
    "scale": (GreenhouseSource, "scaleai", "Scale AI"),                 # 219
    "together": (GreenhouseSource, "togetherai", "Together AI"),        # 62
    "harvey": (AshbySource, "harvey", "Harvey"),                        # 350
    "glean": (SmartRecruitersSource, "glean", "Glean"),                 # 1
    "ramp": (AshbySource, "ramp", "Ramp"),                              # 139
    "brex": (GreenhouseSource, "brex", "Brex"),                         # 294
    "remote": (GreenhouseSource, "remotecom", "Remote"),                # 204
}

#: Employers with no public ATS board on any of the four supported providers. Kept explicit so
#: the gap is visible rather than looking like an oversight — each was probed across
#: Greenhouse, Lever, Ashby and SmartRecruiters and returned nothing.
NO_PUBLIC_BOARD: tuple[str, ...] = (
    "starling", "revolut", "deliveroo",
    # Probed 2026-08-30 alongside the expansion above — large enterprises typically run
    # Workday or a custom career site, neither of which these four providers can reach.
    "nvidia", "c3ai", "lseg", "bloomberg", "capitalone", "justeat", "booking", "expedia", "king",
)


def build_career_sources() -> dict[str, type[AtsBoardSource]]:
    """Create one adapter class per employer, keyed ``careers:<slug>``.

    The registry stores classes and instantiates them with no arguments, so the employer's
    token and display name are baked in as class attributes rather than passed at call time.
    """
    built: dict[str, type[AtsBoardSource]] = {}
    for slug, (base, token, label) in COMPANY_BOARDS.items():
        key = f"careers:{slug}"
        built[key] = type(
            f"{base.__name__.replace('Source', '')}{slug.title().replace('-', '')}Source",
            (base,),
            {"source_name": key, "board_token": token, "company_name": label},
        )
    return built


def _unescape(text: str) -> str:
    """Reverse HTML entity escaping applied to an already-HTML payload."""
    import html

    return html.unescape(text)
