"""Canonical enumerations — the single source of truth for status/mode values.

These replace the duplicate plain-class definitions that previously lived in both
``app.config.constants`` and ``app.schemas.application``. Models map them to native
PostgreSQL enum types (VARCHAR+CHECK on SQLite) via ``app.models.base.pg_enum``;
schemas re-export them. Because they are ``StrEnum``, ``member == "value"`` holds, so
existing string comparisons keep working.
"""

from enum import StrEnum


class ApplicationStatus(StrEnum):
    """Lifecycle of a job application."""

    QUEUED = "queued"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    APPLYING = "applying"
    APPLIED = "applied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"


class JobStatus(StrEnum):
    """Lifecycle of a discovered job listing."""

    NEW = "new"
    SAVED = "saved"
    APPLIED = "applied"
    HIDDEN = "hidden"


class ApplyMode(StrEnum):
    """How an application is dispatched."""

    AUTONOMOUS = "autonomous"
    REVIEW = "review"
    BATCH = "batch"


class ResumeType(StrEnum):
    """Whether a resume is a base, a job-tailored, or an ATS-optimized variant."""

    BASE = "base"
    TAILORED = "tailored"
    OPTIMIZED = "optimized"


class LLMPurpose(StrEnum):
    """Why an LLM call was made (for per-user usage accounting)."""

    RESUME_TAILOR = "resume_tailor"
    COVER_LETTER = "cover_letter"
    ATS_OPTIMIZE = "ats_optimize"
    JOB_ANALYSIS = "job_analysis"
    HARNESS_JUDGE = "harness_judge"
    SKILL_DISTILL = "skill_distill"
    GENERAL = "general"


class RunVerdictResult(StrEnum):
    """LLM-judge verdict on an apply run."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class FailureClass(StrEnum):
    """Taxonomy of apply-run failures (the self-evolving harness classifies into these)."""

    LOGIN_FAILED = "login_failed"
    SESSION_EXPIRED = "session_expired"
    CAPTCHA_WALL = "captcha_wall"
    TWOFA_REQUIRED = "twofa_required"
    ANTIBOT_BLOCK = "antibot_block"
    DOM_DRIFT = "dom_drift"
    FIELD_MISSING = "field_missing"
    AGENT_OFFTRACK = "agent_offtrack"
    LOOP = "loop"
    LLM_ERROR = "llm_error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class SkillStatus(StrEnum):
    """Lifecycle of a distilled domain skill."""

    ACTIVE = "active"
    RETIRED = "retired"
