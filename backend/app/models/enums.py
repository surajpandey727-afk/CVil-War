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


class SponsorConfidence(StrEnum):
    """How confident the system is that an employer sponsors the Skilled Worker (Tier 2) visa.

    A ranking boost by default, never an automatic hard filter on its own — see
    ``core.actions``/``services.job_search``. Three signals feed this today, strongest first:
    a match on the UK Home Office's public register of licensed sponsors
    (``core.sponsorship.register``), explicit sponsorship language in the posting itself
    (``core.sponsorship.keywords.detect``), and an explicit *no*-sponsorship statement in the
    posting (``core.sponsorship.keywords.detect_negation``) — reported as ``NOT_SPONSOR``, not
    collapsed into ``UNKNOWN``, since "the posting says it won't sponsor" is real, actionable
    evidence for a candidate who needs one, unlike a posting that simply never mentions it.
    An operator who specifically needs sponsorship can turn this into a hard exclude via
    ``AutomationPolicy.exclude_no_sponsorship`` — see ``core.policy.rules``. ``LIKELY`` is
    reserved for a future, more speculative signal (e.g. industry-level priors) — nothing
    currently classifies into it, and it is never asserted without real evidence.
    """

    CONFIRMED_REGISTER = "confirmed_register"
    KEYWORD_DETECTED = "keyword_detected"
    LIKELY = "likely"
    UNKNOWN = "unknown"
    NOT_SPONSOR = "not_sponsor"


class AgentName(StrEnum):
    """The single-responsibility agents the orchestration layer tracks.

    Each name maps to one existing service boundary — this enum does not invent new
    responsibilities, it labels ones that already exist so their activity becomes visible:
    Discovery is ``services.discovery_scheduler``, Eligibility is
    ``core.sponsorship.classify``, Scoring is ``services.resume_recommendation``, and
    Application is the apply pipeline in ``workers.tasks``. Tracking (Apollo/Gmail
    communications) is reserved for when that workstream exists.
    """

    DISCOVERY = "discovery"
    ELIGIBILITY = "eligibility"
    SCORING = "scoring"
    APPLICATION = "application"
    TRACKING = "tracking"


class AgentRunStatus(StrEnum):
    """Lifecycle of one agent invocation, recorded in ``AgentRun``."""

    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    NEEDS_REVIEW = "needs_review"


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
    EMAIL_REPLY_RECEIVED = "email_reply_received"
    EMAIL_REJECTION_DETECTED = "email_rejection_detected"
    EMAIL_INTERVIEW_INVITE_DETECTED = "email_interview_invite_detected"
    APOLLO_CONTACT_LOGGED = "apollo_contact_logged"


class DocumentType(StrEnum):
    """Kinds of document the library holds."""

    CV = "cv"
    COVER_LETTER = "cover_letter"
    PORTFOLIO = "portfolio"
    CERTIFICATE = "certificate"
    WORK_SAMPLE = "work_sample"
    REFERENCE = "reference"
    OTHER = "other"


class SubmissionMethod(StrEnum):
    """How an application was actually delivered.

    Recorded because "Applied" alone cannot distinguish a browser that really filled in a
    form from a placeholder run with ``BROWSER__LIVE_APPLY`` off. Both used to leave an
    identical row, so the operator had no way to tell a real submission from a rehearsal.
    """

    #: A browser session drove the portal's own form.
    AUTOMATED = "automated"
    #: The operator submitted it themselves and recorded the outcome.
    MANUAL = "manual"
    #: Sent to an address the posting published.
    EMAIL = "email"
    #: The placeholder path — the pipeline ran but nothing was sent anywhere.
    SIMULATED = "simulated"
    #: Nothing has been submitted yet.
    NONE = "none"


class ConfirmationState(StrEnum):
    """Whether the submission was actually acknowledged by the far end.

    The distinction the product depends on: ``Applied`` should mean an employer received
    something, not that automation started and did not crash.
    """

    #: The portal returned a confirmation the agent could read.
    CONFIRMED = "confirmed"
    #: The run finished without an error but no confirmation was observed.
    UNCONFIRMED = "unconfirmed"
    #: No submission was attempted — the placeholder path.
    SIMULATED = "simulated"
    #: Not submitted yet.
    PENDING = "pending"
    #: The attempt failed before any submission could be confirmed.
    FAILED = "failed"
