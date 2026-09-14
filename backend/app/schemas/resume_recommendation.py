"""Pydantic schemas for the multi-résumé recommendation endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.resume import ResumeScoreResponse


class ResumeRanking(BaseModel):
    """One résumé's score against a job, as part of a full ranking."""

    resume_id: str
    resume_name: str
    score: ResumeScoreResponse


class ResumeRecommendation(BaseModel):
    """Every résumé ranked against one job, with the winner called out and explained."""

    job_id: str
    #: ``None`` only when the user has no résumés at all — see ``synopsis`` for why.
    recommended_resume_id: str | None = None
    rankings: list[ResumeRanking] = Field(default_factory=list)
    #: One short paragraph: who wins, by how much, and what to change. Written for a
    #: floating widget, not a report — kept to a sentence or two.
    synopsis: str = ""
