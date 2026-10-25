"""Tool catalogue: names, descriptions, validated inputs, and which ones need confirmation.

Each tool's JSON schema is generated from its pydantic input model (``extra="forbid"`` →
``additionalProperties: false``), so the schema Claude sees and the validation the server
runs can never drift apart. Inputs are validated *again* server-side before anything
executes — a schema is guidance to the model, not a guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoInput(_Input):
    pass


class SearchStoredJobsInput(_Input):
    query: str | None = Field(default=None, max_length=120, description="Title/skill words.")
    location: str | None = Field(default=None, max_length=80, description="UK place, e.g. London.")
    workplace: Literal["onsite", "hybrid", "remote"] | None = None
    status: Literal["new", "saved", "applied", "hidden"] | None = None
    limit: int = Field(default=10, ge=1, le=20)


class BestMatchesInput(_Input):
    limit: int = Field(default=10, ge=1, le=20)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="0-1 match score floor.")


class JobIdInput(_Input):
    job_id: str = Field(min_length=1, max_length=64)


class CheckResumeInput(_Input):
    job_id: str = Field(min_length=1, max_length=64)
    resume_id: str | None = Field(
        default=None, max_length=64, description="Omit to use the best-matching résumé."
    )


class ListApplicationsInput(_Input):
    status: (
        Literal[
            "queued",
            "pending_review",
            "approved",
            "applying",
            "applied",
            "interview",
            "rejected",
            "offer",
            "withdrawn",
            "failed",
        ]
        | None
    ) = None
    limit: int = Field(default=10, ge=1, le=25)


class LimitInput(_Input):
    limit: int = Field(default=10, ge=1, le=25)


class SkillRadarInput(_Input):
    role_titles: list[str] = Field(min_length=1, max_length=6)


class StageApplicationInput(_Input):
    job_id: str = Field(min_length=1, max_length=64)
    resume_id: str | None = Field(default=None, max_length=64)


class ApproveApplicationsInput(_Input):
    application_ids: list[str] = Field(min_length=1, max_length=20)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    model: type[_Input]
    #: True: the tool only *proposes*; the user confirms before anything changes.
    consequential: bool = False

    def definition(self) -> dict[str, Any]:
        schema = self.model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        schema.setdefault("properties", {})
        schema["type"] = "object"
        schema["additionalProperties"] = False
        return {"name": self.name, "description": self.description, "input_schema": schema}


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "get_overview",
        "Snapshot of the user's job search: UK job counts, applications by status, what needs "
        "attention now, apply mode, and their résumés (ids and names). Call this first when "
        "the user asks what's going on or what to do next.",
        NoInput,
    ),
    ToolSpec(
        "search_stored_jobs",
        "Search the user's stored, UK-eligible jobs by title words, UK location, workplace "
        "type or status. Returns id, title, company, location, salary, sponsor signal and "
        "match score (0-1). Only UK roles are ever returned; that policy cannot be bypassed.",
        SearchStoredJobsInput,
    ),
    ToolSpec(
        "get_best_matches",
        "The user's stored UK jobs ranked by match score (0-1, highest first). Use for "
        "'what should I apply to'.",
        BestMatchesInput,
    ),
    ToolSpec(
        "get_job",
        "Full detail for one stored job: posting excerpt, salary, location verdict, visa "
        "sponsorship signal, whether an application exists, and which résumé fits it best.",
        JobIdInput,
    ),
    ToolSpec(
        "check_resume_against_job",
        "Run the deterministic Résumé checker for one résumé against one job: fit score, "
        "evidenced skills, missing skills, and suggestions. Suggestions marked "
        "add_only_if_true must only be added if the user really has that experience.",
        CheckResumeInput,
    ),
    ToolSpec(
        "list_applications",
        "The user's applications, newest first, optionally filtered by status.",
        ListApplicationsInput,
    ),
    ToolSpec(
        "get_action_queue",
        "Everything that needs the user's action across applications, most urgent first, "
        "with the reason for each.",
        LimitInput,
    ),
    ToolSpec(
        "list_agents",
        "Status of the platform's AI agents (Discovery, Eligibility, Scoring, Résumé, "
        "Application, Tracking, Assistant): last run, counts and what isn't configured.",
        NoInput,
    ),
    ToolSpec(
        "get_skill_radar",
        "Aggregate the skills UK employers ask for across the given role titles.",
        SkillRadarInput,
    ),
    ToolSpec(
        "run_discovery_now",
        "Propose running job discovery now against the user's active role targets. Needs "
        "the user's confirmation; nothing runs until they confirm.",
        NoInput,
        consequential=True,
    ),
    ToolSpec(
        "stage_application",
        "Propose creating an application for one stored UK job. It is staged as "
        "pending_review for the user to approve; it is never submitted. Needs confirmation.",
        StageApplicationInput,
        consequential=True,
    ),
    ToolSpec(
        "approve_applications",
        "Propose approving staged (pending_review) applications so they join the apply "
        "queue. The apply worker and the automation policy still decide whether and when "
        "each one is submitted. Needs confirmation.",
        ApproveApplicationsInput,
        consequential=True,
    ),
)

BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}


def definitions() -> list[dict[str, Any]]:
    """Tool definitions in a fixed order (a stable prefix keeps prompt caching effective)."""
    return [t.definition() for t in TOOLS]
