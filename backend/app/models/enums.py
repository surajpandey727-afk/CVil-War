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


class ApplicationHealth(StrEnum):
    """Operational state of an application — deliberately separate from hiring status.

    An application can be at INTERVIEW (hiring status) and simultaneously BLOCKED
    (operational) because a session expired. Collapsing the two loses exactly the
    information the command centre exists to surface: what needs the user right now.
    """

    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"
    BLOCKED = "blocked"
    STALE = "stale"
    SESSION_REQUIRED = "session_required"
    DOCUMENT_REQUIRED = "document_required"
    ACTION_REQUIRED = "action_required"
    STATUS_UNKNOWN = "status_unknown"


class NextAction(StrEnum):
    """What the user (or system) should do next for an application.

    Every blocker maps to one of these. "Application failed" is never a terminal answer —
    a recoverable failure becomes an actionable state, which is what stops the dashboard
    turning into a list of dead ends.
    """

    RESPOND_TO_RECRUITER = "respond_to_recruiter"
    COMPLETE_ASSESSMENT = "complete_assessment"
    UPLOAD_CV = "upload_cv"
    UPLOAD_DOCUMENT = "upload_document"
    RELOGIN = "relogin"
    COMPLETE_VERIFICATION = "complete_verification"
    CONFIRM_APPLICATION = "confirm_application"
    REVIEW_ANSWER = "review_answer"
    FOLLOW_UP = "follow_up"
    SCHEDULE_INTERVIEW = "schedule_interview"
    PREPARE_INTERVIEW = "prepare_interview"
    REVIEW_APPLICATION = "review_application"
    VERIFY_SUBMISSION = "verify_submission"
    RESUME_APPLICATION = "resume_application"
    UPDATE_PROFILE = "update_profile"
    WAIT = "wait"
    NONE = "none"


class ActionPriority(StrEnum):
    """Bucket used for ordering and colour in the action queue."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class SessionState(StrEnum):
    """Authorised-session lifecycle for one platform.

    Kept granular on purpose: collapsing these into FAILED is what produced dead ends. An
    expired session is a reconnect prompt, MFA is a hand-off, a server block is a different
    access mechanism entirely — three different user actions, not one error.
    """

    SESSION_ACTIVE = "session_active"
    SESSION_EXPIRING = "session_expiring"
    SESSION_EXPIRED = "session_expired"
    AUTH_REQUIRED = "auth_required"
    MFA_REQUIRED = "mfa_required"
    HUMAN_VERIFICATION_REQUIRED = "human_verification_required"
    SERVER_BLOCKED = "server_blocked"
    INTERACTIVE_AVAILABLE = "interactive_available"
    AUTOMATION_UNSUPPORTED = "automation_unsupported"
    NOT_CONNECTED = "not_connected"


class ApplicationEventType(StrEnum):
    """Timeline entries. Every meaningful state change persists one of these."""

    DISCOVERED = "discovered"
    SHORTLISTED = "shortlisted"
    CV_SELECTED = "cv_selected"
    CV_TAILORED = "cv_tailored"
    COVER_LETTER_GENERATED = "cover_letter_generated"
    APPLICATION_STARTED = "application_started"
    APPLICATION_PAUSED = "application_paused"
    APPLICATION_RESUMED = "application_resumed"
    APPLICATION_SUBMITTED = "application_submitted"
    SUBMISSION_VERIFIED = "submission_verified"
    STATUS_CHANGED = "status_changed"
    RECRUITER_CONTACTED = "recruiter_contacted"
    USER_ACTION_REQUIRED = "user_action_required"
    USER_ACTION_COMPLETED = "user_action_completed"
    ASSESSMENT_INVITED = "assessment_invited"
    ASSESSMENT_COMPLETED = "assessment_completed"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    FOLLOW_UP_DUE = "follow_up_due"
    FOLLOW_UP_SENT = "follow_up_sent"
    NOTE_ADDED = "note_added"
    ERROR = "error"


class DocumentType(StrEnum):
    """Kinds of document the library holds."""

    CV = "cv"
    COVER_LETTER = "cover_letter"
    PORTFOLIO = "portfolio"
    CERTIFICATE = "certificate"
    WORK_SAMPLE = "work_sample"
    REFERENCE = "reference"
    OTHER = "other"
