"""Pydantic schemas for user settings API requests and responses."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.policy.model import AutomationPolicy, ResumeRule, RunWindow


class WorkExperienceSchema(BaseModel):
    """A single work experience entry."""

    title: str = ""
    company: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""
    responsibilities: list[str] = Field(default_factory=list)


class EducationSchema(BaseModel):
    """A single education entry."""

    degree: str = ""
    institution: str = ""
    graduation_year: str = ""
    gpa: str | None = None


class CandidateProfileSchema(BaseModel):
    """Structured candidate profile for resume generation."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[WorkExperienceSchema] = Field(default_factory=list)
    education: list[EducationSchema] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


#: Families the product ships with. Deliberately **not** a ``Literal``: a family is a label
#: the operator groups their own targets by, and closing the set meant someone hunting for
#: "design" or "security" roles had to change code to say so. The shipped four remain as
#: sensible defaults and as the seed for a new profile.
DEFAULT_ROLE_FAMILIES = ("product", "engineering", "architecture", "data")
RoleFamily = str


class RoleTargetSchema(BaseModel):
    """One role the operator is targeting, and the criteria that define it.

    Deliberately extensible in two ways, because the previous shape — title, fit, why,
    family, active — could not express a search anyone actually runs. "Product Manager" says
    nothing about seniority, salary, the skills that matter, the companies to avoid, or which
    boards to look on, so every one of those had to live somewhere else or nowhere.

    * Every criterion below is **optional**, so an existing stored target with only the old
      five fields still validates and simply carries no extra criteria.
    * ``extra="allow"`` keeps a criterion added by a newer build from being silently dropped
      when an older one reads and rewrites the row. Losing an operator's configuration
      because a field was unrecognised is worse than carrying a field nobody reads yet.

    None of this is enforced here — the shape is storage. Scoring and filtering read it.
    """

    model_config = ConfigDict(extra="allow")

    title: str
    #: The operator's own 1-5 assessment. Advisory: it orders the table and seeds which
    #: titles are active, but the ATS scorer decides whether a posting is applied to.
    fit: float = Field(default=3.0, ge=0.0, le=5.0)
    why: str = ""
    family: RoleFamily = "engineering"
    active: bool = True

    # -- Matching ------------------------------------------------------------------------
    #: Other titles that mean the same job. Boards are wildly inconsistent about naming.
    alternative_titles: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    #: A posting containing any of these is rejected outright, whatever else it matches.
    excluded_keywords: list[str] = Field(default_factory=list)

    # -- Where and on what terms ---------------------------------------------------------
    locations: list[str] = Field(default_factory=list)
    #: remote | hybrid | onsite | any
    work_mode: str = "any"
    #: Thousands of the local currency. 0 means no floor rather than a floor of zero.
    min_salary_k: int = Field(default=0, ge=0, le=1000)
    max_salary_k: int = Field(default=0, ge=0, le=1000)
    employment_types: list[str] = Field(default_factory=list)

    # -- Who ------------------------------------------------------------------------------
    industries: list[str] = Field(default_factory=list)
    #: Employers to prioritise; empty means no preference, not "none of them".
    target_companies: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    #: Source keys to search for this target. Empty means every enabled source.
    job_boards: list[str] = Field(default_factory=list)

    # -- How the agent should treat it ----------------------------------------------------
    #: Free text handed to the model when scoring or tailoring for this target.
    ai_instructions: str = ""
    #: Ordering hint when several targets compete for the same run budget.
    priority: int = Field(default=3, ge=1, le=5)
    #: manual | assisted | approval | autonomous — how far the agent may go unattended.
    #: Per-target, so a speculative role can stay manual while a strong one runs autonomously.
    strategy: str = "approval"
    #: Model override for this target. Empty means the global default; a value here is the
    #: explicit, visible override the AI hierarchy allows.
    model: str = ""


# The automation blob is the policy. It used to be declared here as a plain settings shape
# while the real rules lived nowhere; now :mod:`app.core.policy` owns the model, the rule
# catalogue evaluates it, and this module re-exports it under the old names so the settings
# API surface is unchanged. One definition, so the stored blob, the engine and the UI cannot
# drift apart.
ResumeRuleSchema = ResumeRule
RunWindowSchema = RunWindow
AutomationSettingsSchema = AutomationPolicy


class SettingsResponse(BaseModel):
    """Current user settings."""

    model_config = ConfigDict(from_attributes=True)

    apply_mode: str = "review"
    min_ats_score: float = 0.75
    max_parallel: int = 3
    preferred_provider: str = "openai"
    platforms_enabled: list[str] = Field(
        default_factory=lambda: ["linkedin", "indeed", "glassdoor"],
    )
    candidate_profile: CandidateProfileSchema = Field(
        default_factory=CandidateProfileSchema,
    )
    role_targets: list[RoleTargetSchema] = Field(default_factory=list)
    automation: AutomationSettingsSchema = Field(default_factory=AutomationSettingsSchema)

    @field_validator("candidate_profile", mode="before")
    @classmethod
    def _coerce_candidate_profile(
        cls, v: Any,
    ) -> CandidateProfileSchema | dict[str, Any]:
        if v is None:
            return CandidateProfileSchema()
        if isinstance(v, dict):
            return CandidateProfileSchema(**v)
        return v

    @field_validator("role_targets", mode="before")
    @classmethod
    def _coerce_role_targets(cls, v: Any) -> list[Any]:
        # The column is nullable, and a settings row created before migration 0007 has NULL.
        return v or []

    @field_validator("automation", mode="before")
    @classmethod
    def _coerce_automation(cls, v: Any) -> AutomationSettingsSchema | dict[str, Any]:
        if v is None:
            return AutomationSettingsSchema()
        if isinstance(v, dict):
            return AutomationSettingsSchema(**v)
        return v


class SettingsUpdate(BaseModel):
    """Request to update user settings. Only provided fields are changed."""

    apply_mode: str | None = None
    min_ats_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_parallel: int | None = Field(default=None, ge=1, le=5)
    preferred_provider: str | None = None
    platforms_enabled: list[str] | None = None
    candidate_profile: CandidateProfileSchema | None = None
    role_targets: list[RoleTargetSchema] | None = None
    automation: AutomationSettingsSchema | None = None


class PolicyControl(BaseModel):
    """How one policy field is edited. Mirrors ``core.policy.ControlSpec`` onto the wire."""

    kind: str
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    options: list[str] = Field(default_factory=list)


class PolicyRuleInfo(BaseModel):
    """One clause of the automation policy, with its control and its current value.

    The automation screen renders itself from a list of these rather than hard-coding the
    controls, so a rule added to the backend catalogue appears in the UI — with its clause
    reference, its rationale and its bounds — without a frontend change.
    """

    id: str
    clause: str
    title: str
    rationale: str
    #: ``gate`` (checked before every submission), ``elsewhere`` (an invariant enforced at
    #: another layer), or ``behaviour`` (changes what the agent does, never refuses).
    enforcement: str
    #: Verdict when a gate rule fires: allow / hold / escalate / block.
    verdict: str
    locked: bool
    control: PolicyControl
    field_name: str = ""
    #: For a locked invariant: where it is actually enforced, so the claim is checkable.
    enforced_by: str = ""
    #: Current value, or ``None`` for a locked invariant with nothing to store.
    value: Any = None


class PolicyGroup(BaseModel):
    """A titled group of rules, in the order the UI should present them."""

    id: str
    title: str
    rules: list[PolicyRuleInfo] = Field(default_factory=list)


class PolicyCatalogue(BaseModel):
    """The whole policy: its clauses, their controls, and the operator's current values."""

    policy_version: int
    document: str = "docs/AUTOMATION_POLICY.md"
    groups: list[PolicyGroup] = Field(default_factory=list)
    policy: AutomationPolicy = Field(default_factory=AutomationPolicy)


class PolicyPreviewItem(BaseModel):
    """What the candidate policy would do to one queued application."""

    application_id: str
    job_title: str = ""
    company: str = ""
    verdict: str
    reasons: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)


class PolicyPreview(BaseModel):
    """A dry run of a candidate policy against everything currently waiting.

    Exists so a threshold is not changed blind. Dragging the ATS minimum from 75 to 85 is a
    reasonable thing to try and an unreasonable thing to guess at: this answers "how many of
    my queued applications would that stop" before the change is saved.
    """

    evaluated: int
    allow: int = 0
    hold: int = 0
    escalate: int = 0
    block: int = 0
    items: list[PolicyPreviewItem] = Field(default_factory=list)


class LLMProviderStatus(BaseModel):
    """Status of a configured LLM provider."""

    provider: str
    configured: bool = False
    model: str = ""
    is_primary: bool = False
