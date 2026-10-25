"""Assistant service: chat (the tool-use loop), confirm (run a signed pending action), prepare
(propose an action from the AI Agents page) and the agents roster.

The Anthropic key is read ONLY from the ``ANTHROPIC_API_KEY`` environment variable, at call
time, and is never logged or returned.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from app.config.settings import get_settings
from app.core.assistant import actions, tokens
from app.core.assistant import tools as t
from app.core.assistant.context import ToolContext
from app.core.assistant.executor import make_executor
from app.core.assistant.loop import (
    DEADLINE_SECONDS,
    AssistantUnavailableError,
    run_loop,
)
from app.core.assistant.prompt import SYSTEM_PROMPT
from app.core.assistant.roster import build_roster
from app.core.llm.client import anthropic_key_configured
from app.schemas.assistant import (
    AgentRosterResponse,
    ChatMessage,
    ChatResponse,
    ConfirmResponse,
    PendingAction,
    PrepareResponse,
    ToolCallSummary,
)

logger = structlog.get_logger(__name__)

FALLBACK_MODEL = "claude-sonnet-5-5"
NO_KEY_MESSAGE = (
    "The assistant isn't set up on this deployment: ANTHROPIC_API_KEY is not configured."
)


def assistant_model() -> str:
    """``LLM__DEFAULT_MODEL`` without the litellm ``anthropic/`` prefix. A non-Claude default
    (a gateway route, say) can't be sent to the Anthropic API, so it falls back."""
    model = get_settings().llm.default_model.strip()
    model = model.removeprefix("anthropic/")
    return model if model.startswith("claude-") else FALLBACK_MODEL


def get_client() -> AsyncAnthropic:
    """A fresh client per request (serverless: no long-lived connection pool to reuse)."""
    return AsyncAnthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=1,
        timeout=DEADLINE_SECONDS,
    )


def _history(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Text-only history → Messages API shape: starts with user, alternates, ends with user."""
    out: list[dict[str, Any]] = []
    for m in messages:
        text = m.content.strip()
        if not text:
            continue
        if not out and m.role == "assistant":
            continue  # a greeting before the first question carries nothing
        if out and out[-1]["role"] == m.role:
            out[-1]["content"] += "\n\n" + text
        else:
            out.append({"role": m.role, "content": text})
    if not out or out[-1]["role"] != "user":
        raise ValueError("The conversation must end with a message from you.")
    return out


async def chat(ctx: ToolContext, messages: list[ChatMessage]) -> ChatResponse:
    if not anthropic_key_configured():
        raise AssistantUnavailableError(NO_KEY_MESSAGE, 503)
    history = _history(messages)
    model = assistant_model()
    result = await run_loop(
        get_client(),
        model=model,
        # Static prompt with a cache breakpoint: tools + system are identical every request.
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=t.definitions(),
        messages=history,
        execute=make_executor(ctx),
    )
    logger.info(
        "assistant.chat",
        iterations=result.iterations,
        tools=len(result.tool_calls),
        pending=len(result.pending),
        stop_reason=result.stop_reason,
    )
    return ChatResponse(
        reply=result.reply,
        tool_calls=[ToolCallSummary(**vars(c)) for c in result.tool_calls],
        pending=[PendingAction(**p) for p in result.pending],
        model=result.model,
    )


async def confirm(ctx: ToolContext, token: str) -> ConfirmResponse:
    try:
        pending = tokens.verify(token, ctx.user_id)
    except tokens.TokenError as exc:
        return ConfirmResponse(ok=False, message=str(exc))
    if not await tokens.claim_once(pending, ctx.redis):
        return ConfirmResponse(ok=False, message="This action was already confirmed.")
    ok, message = await actions.execute(ctx, pending)
    logger.info("assistant.confirmed", action=pending.action, ok=ok)
    return ConfirmResponse(ok=ok, message=message)


async def prepare(ctx: ToolContext, action: str) -> PrepareResponse:
    """Propose an agent action without the chat (AI Agents page buttons)."""
    if action != actions.DISCOVER:
        return PrepareResponse(ok=False, message="Unknown action.")
    outcome = await actions.propose_discovery(ctx, t.NoInput())
    if outcome.pending is None:
        return PrepareResponse(ok=False, message=outcome.content)
    return PrepareResponse(ok=True, pending=PendingAction(**outcome.pending))


async def roster(ctx: ToolContext) -> AgentRosterResponse:
    return AgentRosterResponse(
        agents=await build_roster(ctx), assistant_available=anthropic_key_configured()
    )
