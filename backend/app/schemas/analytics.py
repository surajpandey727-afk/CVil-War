"""Pydantic schemas for analytics and dashboard API responses."""

from pydantic import BaseModel, Field


class DashboardStats(BaseModel):
    """Top-level dashboard statistics."""

    total_jobs_found: int = 0
    total_applications: int = 0
    applications_pending: int = 0
    applications_applied: int = 0
    applications_interview: int = 0
    applications_rejected: int = 0
    applications_offer: int = 0
    applications_failed: int = 0
    #: Agent activity right now, so the dashboard can answer "what is it doing".
    applications_queued: int = 0
    applications_applying: int = 0
    #: Submissions that actually went out in the last 24 hours / 7 days. Counted on
    #: ``applied_at``, not ``created_at``: a queued application is not an application sent.
    submitted_today: int = 0
    submitted_this_week: int = 0
    avg_ats_score: float = 0.0
    total_llm_cost_usd: float = 0.0
    #: Jobs first seen since local midnight, vs. ``total_jobs_found``'s all-time total —
    #: the two answer different questions ("is discovery running today" vs. "how big is
    #: the cache").
    jobs_found_today: int = 0
    #: Distinct vacancies after cross-source dedup (``Job.canonical_job_id``) — the number
    #: that matters to a candidate, who does not care that one role is stored as three rows
    #: because three boards carried it.
    unique_jobs: int = 0
    #: Counted, not source_registry's whole catalogue — an unimplemented or credential-
    #: gated source has zero jobs and does not belong on a chart about what is actually
    #: returning results.
    jobs_by_source: dict[str, int] = Field(default_factory=dict)
    #: Register-confirmed only (SponsorConfidence.CONFIRMED_REGISTER) — the strongest tier,
    #: not "any positive signal", so this number can be quoted without a caveat.
    sponsor_confirmed_jobs: int = 0
    #: Résumés the agent produced (tailored or ATS-optimized) — excludes the operator's own
    #: uploaded base CV, which was written by them, not generated.
    cvs_generated: int = 0
    #: ``None`` when the register has never been fetched — see
    #: ``core.sponsorship.register.status()``, the same source of truth the Settings screen
    #: uses, so the two can never disagree about freshness.
    sponsor_register_last_refreshed: str | None = None


class ApplicationFunnelData(BaseModel):
    """Application funnel stage counts."""

    stage: str
    count: int


class ATSScoreDistribution(BaseModel):
    """ATS score histogram bucket."""

    range_label: str
    count: int


class LLMUsageStats(BaseModel):
    """LLM usage aggregation."""

    provider: str
    model: str
    total_requests: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0


class TimelineEntry(BaseModel):
    """Daily activity timeline entry."""

    date: str
    applications_created: int = 0
    applications_applied: int = 0
    jobs_found: int = 0
