"""The automation policy: what the agent is allowed to do, as data.

The prose version lives in ``docs/AUTOMATION_POLICY.md``; this module is the machine-readable
counterpart, and the two are meant to be read together. Every clause in the document names the
rule id that enforces it.

Three things live here:

* :class:`AutomationPolicy` — the stored, operator-editable configuration. It is a superset of
  the shape the settings screen already persisted, so an existing ``UserSettings.automation``
  blob loads unchanged and the new clauses take their defaults.
* :class:`ControlSpec` — how one field is presented and bounded. This is what makes the UI
  schema-driven: the automation screen renders controls from the rule catalogue rather than
  hard-coding them, so a rule added here appears in the UI with no frontend change.
* :class:`PolicyContext` / :class:`PolicyDecision` — the facts a decision is made from, and
  the decision itself.

Deliberately free of I/O and of any app import beyond Pydantic: the engine must be evaluable
in a test with a hand-built context and no database.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Bumped when a stored policy needs migrating rather than merely defaulting.
POLICY_VERSION = 1


class Verdict(StrEnum):
    """What the policy says about one candidate submission.

    The distinction between the three refusals is the point. Collapsing them into a single
    "no" is how automation ends up either silently dropping work or retrying forever.
    """

    #: Nothing objects. Submit.
    ALLOW = "allow"
    #: Not now, but plausibly later — a cap, a window, a cooldown. Stays queued.
    HOLD = "hold"
    #: A human must decide. Enters the action queue; never auto-resolved.
    ESCALATE = "escalate"
    #: Never, for this application. Terminal.
    BLOCK = "block"


#: Worst-wins ordering. A decision takes the highest-precedence verdict any rule produced,
#: while still reporting every rule that fired — see ``PolicyDecision.outcomes``.
_SEVERITY: dict[Verdict, int] = {
    Verdict.ALLOW: 0,
    Verdict.HOLD: 1,
    Verdict.ESCALATE: 2,
    Verdict.BLOCK: 3,
}


def worst(verdicts: list[Verdict]) -> Verdict:
    """The most restrictive verdict in the list, or ALLOW if empty."""
    return max(verdicts, key=lambda v: _SEVERITY[v], default=Verdict.ALLOW)


class ControlKind(StrEnum):
    """How a policy field is edited. Drives which control the UI renders."""

    TOGGLE = "toggle"
    INTEGER = "integer"
    PERCENT = "percent"
    MONEY_K = "money_k"
    DAYS = "days"
    SECONDS = "seconds"
    CHOICE = "choice"
    MULTI_CHOICE = "multi_choice"
    TEXT_LIST = "text_list"
    TIME = "time"
    WEEKDAYS = "weekdays"
    #: Shown for transparency, not editable — the invariants in policy §1.
    LOCKED = "locked"


class ControlSpec(BaseModel):
    """Presentation and bounds for one editable field.

    The bounds are advisory to the UI and authoritative in Pydantic: the same numbers appear
    as ``Field(ge=..., le=...)`` on :class:`AutomationPolicy`, so a client that ignores the
    spec still cannot store an out-of-range value.
    """

    kind: ControlKind
    min: float | None = None
    max: float | None = None
    step: float | None = None
    #: Suffix shown next to the value ("per day", "%", "£k").
    unit: str = ""
    options: list[str] = Field(default_factory=list)
    #: Value that disables the rule entirely, when one exists (usually 0 or an empty list).
    off_value: Any = None


class RunWindow(BaseModel):
    """Hours during which the worker may submit. Outside them, runs queue but do not send."""

    #: Three-letter day abbreviations. Empty means every day.
    days: list[str] = Field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])
    start: str = "08:00"
    end: str = "19:00"
    timezone: str = "Europe/London"


class ResumeRule(BaseModel):
    """Pick a résumé by matching the job title or the employer.

    Rules are evaluated in list order and the first match wins; a job that matches nothing
    falls back to :attr:`AutomationPolicy.default_resume_id`.
    """

    #: Case-insensitive regular expression matched against the job title.
    title_pattern: str = ""
    #: Case-insensitive regular expression matched against the company name.
    company_pattern: str = ""
    #: Résumé id to use when this rule matches.
    resume_id: str = ""
    label: str = ""


class AutomationPolicy(BaseModel):
    """The operator-editable half of the automation policy.

    Superset of the shape the settings screen persisted before the policy engine existed, so
    a stored blob written by the old UI validates here and picks up defaults for everything
    new. ``extra="ignore"`` keeps a policy written by a *newer* build from failing to load on
    an older one — the unknown clause is simply not enforced, which is the safe direction.

    The §1 integrity invariants are absent by design. They are not configuration, so they get
    no field; :mod:`app.core.policy.rules` enforces them unconditionally.
    """

    model_config = ConfigDict(extra="ignore")

    version: int = POLICY_VERSION

    # -- §4 human oversight -------------------------------------------------------------
    #: Master stop. Everything queued stays queued; nothing is submitted.
    paused: bool = False
    require_review_above_salary_k: int = Field(default=120, ge=0, le=1000)
    review_first_run_per_source: bool = True
    pause_on_captcha: bool = True
    #: The browser window is visible while the agent works, not headless — so you can watch
    #: an application happen in real time instead of only ever seeing its result afterwards.
    run_headed: bool = True
    #: The agent fills the form, then stops and waits for your explicit go-ahead before
    #: clicking the final submit control. Off means it submits the moment it decides the form
    #: is complete, with no human in that last step.
    require_submission_confirmation: bool = True

    # -- §5 match and eligibility -------------------------------------------------------
    #: 0-1, mirroring ``UserSettings.min_ats_score``. Below this, never auto-applied.
    min_ats_score: float = Field(default=0.75, ge=0.0, le=1.0)
    #: Thousands of GBP. 0 disables the filter.
    min_salary_k: int = Field(default=0, ge=0, le=1000)
    #: Empty means any seniority.
    seniority: list[str] = Field(default_factory=list)
    #: Job.job_type values excluded from search results outright (not just from auto-apply) —
    #: see services.job_search.list_jobs. Matched case-insensitively against the raw string a
    #: board supplied, since employment type is free text, not a closed enum, across sources.
    exclude_employment_types: list[str] = Field(
        default_factory=lambda: ["contract", "part-time", "part_time", "internship"]
    )
    #: Employers never applied to, matched case-insensitively on the company name.
    blocked_companies: list[str] = Field(default_factory=list)
    #: Off by default. When on, a posting whose own text explicitly states it does not sponsor
    #: a visa (``SponsorConfidence.NOT_SPONSOR``) is blocked outright rather than merely ranked
    #: lower. Never fires on a posting that simply doesn't mention sponsorship either way.
    exclude_no_sponsorship: bool = False

    # -- §2 volume and rate -------------------------------------------------------------
    max_per_day: int = Field(default=20, ge=0, le=200)
    max_per_hour: int = Field(default=5, ge=0, le=50)
    min_seconds_between: int = Field(default=90, ge=0, le=3600)
    max_per_company_per_week: int = Field(default=2, ge=0, le=20)

    # -- §3 duplicate suppression -------------------------------------------------------
    reapply_cooldown_days: int = Field(default=90, ge=0, le=730)

    # -- §7 failure handling ------------------------------------------------------------
    retry_failed: bool = True
    max_retries: int = Field(default=3, ge=0, le=10)
    circuit_breaker_failures: int = Field(default=3, ge=0, le=20)
    email_fallback: bool = True
    notify_each_outcome: bool = True

    # -- §6 run window ------------------------------------------------------------------
    run_window: RunWindow = Field(default_factory=RunWindow)

    # -- documents ----------------------------------------------------------------------
    default_resume_id: str | None = None
    resume_rules: list[ResumeRule] = Field(default_factory=list)
    cover_letters: bool = True
    cover_letter_tone: Literal["direct", "warm", "formal", "technical"] = "direct"

    # -- §8 data protection -------------------------------------------------------------
    #: Days to keep generated CVs and cover letters. 0 means keep indefinitely.
    retain_documents_days: int = Field(default=0, ge=0, le=3650)

    # -- §1.5 disclosure ----------------------------------------------------------------
    disclose_ai_assistance: bool = False

    #: Source keys the operator has enabled. Empty means "every implemented source".
    enabled_sources: list[str] = Field(default_factory=list)

    @field_validator(
        "seniority", "exclude_employment_types", "blocked_companies", "enabled_sources",
        mode="before",
    )
    @classmethod
    def _drop_non_string_entries(cls, v: object) -> list[object]:
        """Degrade, don't 500 — same tolerance as ``CandidateProfileSchema``.

        This is stored JSON like any other operator setting; a malformed entry here
        would raise the same unhandled ``ValidationError`` out of ``GET /settings/``
        already confirmed live for the candidate profile and role-target lists.
        """
        if not isinstance(v, list):
            return []
        return [s for s in v if isinstance(s, str)]

    @field_validator("resume_rules", mode="before")
    @classmethod
    def _drop_non_dict_resume_rules(cls, v: object) -> list[object]:
        if not isinstance(v, list):
            return []
        return [r for r in v if isinstance(r, dict)]


class PolicyContext(BaseModel):
    """Everything a rule may consult about one candidate submission.

    Assembled by :mod:`app.services.policy` from the database. Kept as an explicit model
    rather than passing the ORM objects around so the rules stay pure and testable, and so
    it is obvious what a rule is permitted to know.

    Optional fields mean *not established*, which is different from a zero. A rule that needs
    a fact it does not have escalates rather than passing — see policy §0 on failing closed.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    now: datetime

    # The posting under consideration.
    job_title: str = ""
    company: str = ""
    source_key: str = ""
    salary_max_k: int | None = None
    seniority: str = ""

    #: 0-1. ``None`` means scoring did not run or could not run — not "scored zero".
    ats_score: float | None = None
    #: The raw ``SponsorConfidence`` string value (e.g. ``"not_sponsor"``), or ``""`` when
    #: unknown/unclassified. Kept as a plain string, not the enum, so this module stays free
    #: of any import beyond Pydantic.
    sponsor_confidence: str = ""

    # Facts about the operator's recent behaviour, counted over the tenant's own rows.
    submitted_today: int = 0
    submitted_this_hour: int = 0
    submitted_to_company_this_week: int = 0
    seconds_since_last_submission: int | None = None

    #: An earlier application to this exact posting exists (any status).
    duplicate_of_application_id: str | None = None
    #: When a materially similar role at this employer was last applied to.
    last_similar_application_at: datetime | None = None

    #: Consecutive failed runs on this source, for the circuit breaker.
    consecutive_source_failures: int = 0
    #: True until at least one application has been submitted through this source.
    first_run_on_source: bool = False

    #: Application-form questions the agent must not answer itself (policy §1.2).
    eligibility_questions: list[str] = Field(default_factory=list)
    #: A CAPTCHA / MFA / identity challenge was raised during the run (policy §1.3).
    challenge_detected: bool = False


class RuleOutcome(BaseModel):
    """One rule's finding. Recorded whether it fired or not."""

    rule_id: str
    clause: str
    verdict: Verdict
    #: Human-readable and specific — this string is shown to the operator verbatim, so it
    #: must say what happened and what would change it, not just name the rule.
    reason: str = ""
    #: When a HOLD could clear, if the rule can say. Drives the retry schedule.
    retry_after: datetime | None = None


class PolicyDecision(BaseModel):
    """The verdict on one candidate submission, plus every reason behind it."""

    verdict: Verdict
    outcomes: list[RuleOutcome] = Field(default_factory=list)
    #: Earliest moment a HOLD could clear, across every holding rule.
    retry_after: datetime | None = None
    policy_version: int = POLICY_VERSION

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def summary(self) -> str:
        """One line for the timeline. Every firing reason, most severe first."""
        if not self.outcomes:
            return "Policy: allowed — no rule objected."
        ranked = sorted(self.outcomes, key=lambda o: -_SEVERITY[o.verdict])
        return "; ".join(o.reason for o in ranked if o.reason)
