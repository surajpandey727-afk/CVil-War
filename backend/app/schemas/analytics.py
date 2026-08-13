"""Pydantic schemas for analytics and dashboard API responses."""

from pydantic import BaseModel


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
