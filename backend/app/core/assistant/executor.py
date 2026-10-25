"""Validate a tool call's input, then run its handler in the request's tenant context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from pydantic import ValidationError

from app.core.assistant import actions, reads
from app.core.assistant import tools as t
from app.core.assistant.context import ToolContext
from app.core.assistant.loop import ToolOutcome
from app.core.exceptions import RecordNotFoundError

logger = structlog.get_logger(__name__)

Handler = Callable[[ToolContext, Any], Awaitable[ToolOutcome]]

HANDLERS: dict[str, Handler] = {
    "get_overview": reads.get_overview,
    "search_stored_jobs": reads.search_stored_jobs,
    "get_best_matches": reads.get_best_matches,
    "get_job": reads.get_job,
    "check_resume_against_job": reads.check_resume_against_job,
    "list_applications": reads.list_applications,
    "get_action_queue": reads.get_action_queue,
    "list_agents": reads.list_agents,
    "get_skill_radar": reads.get_skill_radar,
    "run_discovery_now": actions.propose_discovery,
    "stage_application": actions.propose_stage,
    "approve_applications": actions.propose_approve,
}


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ())) or "input"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "Invalid input — " + "; ".join(parts)


def make_executor(ctx: ToolContext) -> Callable[[str, Any], Awaitable[ToolOutcome]]:
    """Bind the tool dispatcher to one request's context."""

    async def execute(name: str, raw: Any) -> ToolOutcome:
        spec = t.BY_NAME.get(name)
        handler = HANDLERS.get(name)
        if spec is None or handler is None:
            return ToolOutcome(ok=False, content=f"Unknown tool: {name}", summary="unknown tool")
        try:
            args = spec.model.model_validate(raw if isinstance(raw, dict) else {})
        except ValidationError as exc:
            return ToolOutcome(ok=False, content=_validation_message(exc), summary="invalid input")
        try:
            return await handler(ctx, args)
        except RecordNotFoundError:
            await ctx.db.rollback()
            return ToolOutcome(ok=False, content="Not found.", summary="not found")
        except Exception as exc:
            # Leave the session usable for the next tool in this turn.
            await ctx.db.rollback()
            logger.warning("assistant.tool_error", tool=name, error=type(exc).__name__)
            return ToolOutcome(
                ok=False,
                content=f"The {name} tool failed ({type(exc).__name__}).",
                summary="failed",
            )

    return execute
