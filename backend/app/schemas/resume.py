"""Pydantic schemas for resume-related API requests and responses."""

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.schemas.settings import EducationSchema, WorkExperienceSchema


class ResumeUploadResponse(BaseModel):
    """Response after uploading a resume file."""

    id: str
    name: str
    file_format: str
    word_count: int
    skills_detected: list[str] = Field(default_factory=list)


class ResumeGenerateRequest(BaseModel):
    """Request to generate a tailored resume."""

    base_resume_id: str
    job_id: str
    template_id: str = "modern"
    output_formats: list[str] = Field(default_factory=lambda: ["pdf", "docx"])


class ResumeScoreRequest(BaseModel):
    """Request to score a resume against a job."""

    job_id: str


class ResumeScoreResponse(BaseModel):
    """Response with ATS score details."""

    resume_id: str
    job_id: str
    overall_score: float
    skill_score: float
    experience_score: float
    education_score: float
    keyword_score: float
    missing_skills: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ResumeOptimizeRequest(BaseModel):
    """Request to optimize a resume for ATS compatibility."""

    job_id: str | None = None


class WeakBullet(BaseModel):
    """One résumé line the reviewer judged weak, with a concrete rewrite."""

    original: str
    why_weak: str
    rewrite: str


class LLMAtsReview(BaseModel):
    """An on-demand, LLM-read second opinion layered on top of the algorithmic ATS score.

    Deliberately NOT folded into the always-on ``ResumeScoreResponse`` — that score runs on
    every passive view (the résumé recommendation ranking, the floating widget, the dispatch
    pipeline's policy gate) and an LLM call on every one of those would be slow and expensive
    for no benefit most of the time. This is the explicit, user-triggered "read it like a real
    reviewer would" pass: contextual skill inference an exact-string matcher cannot do (e.g.
    crediting "CI/CD" for a résumé that only says "Jenkins, GitHub Actions"), recency judgment
    an aggregate years-of-experience number cannot express, and bullet-level rewrites.
    """

    semantic_score: float = Field(ge=0.0, le=1.0)
    #: Skills the job asks for that the algorithmic matcher already found present or absent
    #: exactly — this is only what the LLM additionally judged present via a DIFFERENT term
    #: than the job posting used (so the UI can say *why* an "already missing" skill is
    #: actually covered), not a full second skills list.
    contextually_satisfied_skills: list[str] = Field(default_factory=list)
    #: Skills still genuinely absent even after contextual/synonym reasoning — the reviewer's
    #: real gap list, replacing the algorithmic matcher's exact-string one for display.
    still_missing_skills: list[str] = Field(default_factory=list)
    recency_note: str = Field(default="")
    seniority_note: str = Field(default="")
    weak_bullets: list[WeakBullet] = Field(default_factory=list)
    #: One paragraph, the way a real recruiter reads a résumé in the first ten seconds.
    verdict: str = Field(default="")


class ResumeAtsReviewResponse(BaseModel):
    """What the on-demand deep review found, plus whether it actually ran."""

    resume_id: str
    job_id: str
    review: LLMAtsReview | None = None
    #: False when no LLM key/gateway was reachable — the caller renders "unavailable", not a
    #: silently empty review that reads as "found nothing wrong".
    available: bool
    detail: str = ""


class ResumeResponse(BaseModel):
    """Single resume in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    template_id: str
    base_resume_id: str | None = None
    job_id: str | None = None
    has_pdf: bool = False
    has_docx: bool = False
    ats_score: float | None = None
    #: Applications this CV is attached to, and how many of those actually went out.
    #: Shown on the card so deleting is an informed decision rather than a surprise.
    used_in_applications: int = 0
    submitted_applications: int = 0
    archived: bool = False
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _convert_paths_to_flags(cls, data: Any) -> Any:
        """Convert internal file paths to boolean flags to avoid leaking server paths.

        ``archived_at`` is collapsed to a boolean for the same reason the paths are: the
        client needs to know the state, not the server's record of when it changed.
        """
        if hasattr(data, "__dict__"):
            # ORM model — check attributes
            return {
                **{k: v for k, v in data.__dict__.items() if not k.startswith("_")},
                "has_pdf": bool(getattr(data, "file_path_pdf", None)),
                "has_docx": bool(getattr(data, "file_path_docx", None)),
                "archived": getattr(data, "archived_at", None) is not None,
            }
        if isinstance(data, dict):
            return {
                **data,
                "has_pdf": bool(data.get("file_path_pdf")),
                "has_docx": bool(data.get("file_path_docx")),
                "archived": data.get("archived") or data.get("archived_at") is not None,
            }
        return data


class ResumeListResponse(BaseModel):
    """Paginated list of resumes."""

    items: list[ResumeResponse]
    total: int
    #: Archived résumés held back from ``items``. Reported so the UI can offer to show them
    #: rather than leaving the user wondering where a CV went.
    archived_count: int = 0


class ResumeUsageItem(BaseModel):
    """One application a résumé was attached to."""

    application_id: str
    job_title: str = ""
    company: str = ""
    status: str
    #: True when this application reached the employer. A CV attached only to drafts is a
    #: working file; one attached to a submitted application is a record of what was sent.
    submitted: bool = False
    applied_at: datetime | None = None
    ats_score: float | None = None


class ResumeUsageResponse(BaseModel):
    """Where a résumé has been used, so deleting it is never a guess."""

    resume_id: str
    total: int
    #: How many of those actually went out. This is the number that decides delete vs archive.
    submitted: int
    items: list[ResumeUsageItem] = Field(default_factory=list)


class ResumeDeleteResponse(BaseModel):
    """What happened to a résumé the user asked to remove.

    Deleting and archiving are reported separately rather than both as a bare 204: a user who
    asked to delete a CV and finds it archived instead is owed the reason, and a UI that
    cannot tell the two apart will show the wrong thing.
    """

    resume_id: str
    deleted: bool
    archived: bool
    used_by: int = 0
    detail: str = ""


class ExtractedProfileData(BaseModel):
    """The LLM's structured read of one résumé's work history and education.

    Deliberately narrow — just the two fields ATS scoring actually needs (see
    ``services.resume._experience_entries_for_scoring``) — not the full candidate profile.
    Contact fields (email/phone/links) are left alone rather than extracted here: those
    belong to the account itself, not to whichever résumé happened to be analyzed.

    ``validation_alias`` on both fields tolerates the LLM's own natural synonyms for these
    keys. Confirmed live on a real résumé: the model returned a completely correct,
    detailed work history under the key ``work_experience`` instead of ``experience`` —
    Pydantic doesn't error on an unrecognised top-level key, it just falls back to each
    field's default, so the call "succeeded" while silently discarding a perfect answer and
    reporting 0 roles found. This is the fix, not a prompt tweak alone — a prompt can ask an
    LLM to use an exact key; it cannot guarantee it will.
    """

    experience: list[WorkExperienceSchema] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "experience", "work_experience", "employment", "work_history",
        ),
    )
    education: list[EducationSchema] = Field(
        default_factory=list,
        validation_alias=AliasChoices("education", "education_history", "qualifications"),
    )


class ExtractProfileResponse(BaseModel):
    """What extraction found and what it did with it."""

    resume_id: str
    experience_found: int
    education_found: int
    #: False when the profile already had entries and was left alone — see
    #: ``services.resume.extract_candidate_profile_from_resume``'s overwrite guard.
    profile_updated: bool
    detail: str = ""
