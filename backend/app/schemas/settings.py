"""Pydantic schemas for user settings API requests and responses."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


RoleFamily = Literal["product", "engineering", "architecture", "data"]


class RoleTargetSchema(BaseModel):
    """One role title the operator is targeting.

    ``fit`` is the operator's own 1-5 assessment and is advisory: it orders the table and
    seeds which titles are active, but the ATS scorer, not this number, decides whether a
    given posting is applied to.
    """

    title: str
    fit: float = Field(default=3.0, ge=0.0, le=5.0)
    why: str = ""
    family: RoleFamily = "engineering"
    active: bool = True


class ResumeRuleSchema(BaseModel):
    """Pick a résumé by matching the job title or the employer.

    Rules are evaluated in list order and the first match wins; a job that matches nothing
    falls back to ``AutomationSettingsSchema.default_resume_id``.
    """

    #: Case-insensitive regular expression matched against the job title.
    title_pattern: str = ""
    #: Case-insensitive regular expression matched against the company name.
    company_pattern: str = ""
    #: Résumé id to use when this rule matches.
    resume_id: str = ""
    label: str = ""


class RunWindowSchema(BaseModel):
    """Hours during which the worker may submit. Outside them, runs queue but do not send."""

    #: Three-letter day abbreviations, e.g. ``["Mon", "Tue"]``. Empty means every day.
    days: list[str] = Field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])
    start: str = "08:00"
    end: str = "19:00"
    timezone: str = "Europe/London"


class AutomationSettingsSchema(BaseModel):
    """Everything the auto-apply agent consults before and during a run."""

    #: 0-1, matching ``UserSettings.min_ats_score``. Postings below this are never auto-applied.
    min_ats_score: float = Field(default=0.75, ge=0.0, le=1.0)
    #: Thousands of GBP. 0 disables the filter.
    min_salary_k: int = Field(default=0, ge=0, le=1000)
    #: Empty means any seniority.
    seniority: list[str] = Field(default_factory=list)
    #: Employers never applied to, matched case-insensitively on the company name.
    blocked_companies: list[str] = Field(default_factory=list)

    default_resume_id: str | None = None
    resume_rules: list[ResumeRuleSchema] = Field(default_factory=list)

    cover_letters: bool = True
    cover_letter_tone: Literal["direct", "warm", "formal", "technical"] = "direct"

    retry_failed: bool = True
    max_retries: int = Field(default=3, ge=0, le=10)
    pause_on_captcha: bool = True
    email_fallback: bool = True
    notify_each_outcome: bool = True

    run_window: RunWindowSchema = Field(default_factory=RunWindowSchema)

    #: Source keys the operator has enabled. Empty means "every implemented source".
    enabled_sources: list[str] = Field(default_factory=list)


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


class LLMProviderStatus(BaseModel):
    """Status of a configured LLM provider."""

    provider: str
    configured: bool = False
    model: str = ""
    is_primary: bool = False
