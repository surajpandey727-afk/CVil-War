"""Request/response schemas for the Skill Radar.

Scores cross the wire on the API's 0-1 convention (multiply by 100 to display), the same as
every other score in the system - see ``lib/status.ts::atsPercent`` and BUG-003.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillAggregateRequest(BaseModel):
    #: The role titles the candidate selected. 1-20 keeps the aggregate meaningful and the
    #: request cheap; an empty list has nothing to aggregate.
    titles: list[str] = Field(..., min_length=1, max_length=20)


class AggregatedSkillOut(BaseModel):
    key: str
    label: str
    category: str
    demand: int
    roles_wanting: int
    must_have: bool
    ats: bool
    #: Live posting frequency when the corpus held jobs, else ``None`` - never 0 for "we didn't
    #: look", which the UI renders differently from "no posting mentions it".
    corpus_count: int | None = None


class SkillAggregateResponse(BaseModel):
    titles: list[str]
    #: Categories in display order, so the client groups without a second source of truth.
    categories: list[str]
    skills: list[AggregatedSkillOut]
    #: True when any skill carries a live corpus count - the client shows a "live" badge.
    corpus_used: bool = False


class SkillScoreRequest(BaseModel):
    resume_id: str
    titles: list[str] = Field(..., min_length=1, max_length=20)


class SkillHitOut(BaseModel):
    key: str
    label: str
    category: str
    demand: int
    roles_wanting: int
    must_have: bool
    ats: bool
    present: bool
    matched_form: str | None = None


class SkillScoreResponse(BaseModel):
    resume_id: str
    resume_name: str
    titles: list[str]
    #: 0-1 weighted coverage. Multiply by 100 to display.
    score: float
    #: 0-1 coverage of the must-have skills only.
    must_have_score: float
    band: str  # "strong" | "decent" | "gap"
    matched_count: int
    total_count: int
    hits: list[SkillHitOut]
    #: Highest-value missing skills, must-haves first.
    top_to_add: list[SkillHitOut]
