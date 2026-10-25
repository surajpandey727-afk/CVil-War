"""The manual Claude tool-use loop behind the Assistant.

Rules this loop keeps (each one has a unit test):
  * every turn's FULL ``response.content`` goes back as the assistant message — never only
    its text — so thinking blocks are passed back unchanged;
  * all ``tool_result`` blocks for one turn go back in ONE user message, failures included
    (``is_error: true``), never dropped;
  * ``stop_reason`` is checked (``refusal``, ``max_tokens``) before content is used;
  * at most ``max_iterations`` model calls and ``deadline_s`` seconds in total, because the
    serverless function limit is 120 s;
  * ``tool_choice`` is ``auto`` only (forced tool use is a 400 on this model) and no
    ``temperature`` is sent.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic
import structlog

logger = structlog.get_logger(__name__)

MAX_ITERATIONS = 6
DEADLINE_SECONDS = 90.0
MAX_TOKENS = 16000
#: Below this much time left, starting another model call would likely blow the deadline.
_MIN_CALL_BUDGET = 8.0


class AssistantUnavailableError(Exception):
    """The model could not be reached or refused the credentials. Message is user-safe."""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class ToolOutcome:
    ok: bool
    #: Text fed back to Claude as the tool_result content (JSON or a plain sentence).
    content: str
    #: One line for the UI chip.
    summary: str
    #: Set by consequential tools: ``{"token": ..., "summary": ...}``.
    pending: dict[str, str] | None = None


@dataclass
class ToolCallRecord:
    name: str
    input_summary: str
    ok: bool
    result_summary: str


@dataclass
class LoopResult:
    reply: str
    model: str
    stop_reason: str | None
    iterations: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    pending: list[dict[str, str]] = field(default_factory=list)


ToolExecutor = Callable[[str, Any], Awaitable[ToolOutcome]]


def _text_of(content: list[Any]) -> str:
    return "\n\n".join(
        b.text for b in content if getattr(b, "type", None) == "text" and getattr(b, "text", "")
    ).strip()


def _input_summary(raw: Any) -> str:
    if not isinstance(raw, dict) or not raw:
        return ""
    parts = [f"{k}={v}" for k, v in raw.items() if v not in (None, "", [])]
    return ", ".join(parts)[:160]


async def run_loop(
    client: Any,
    *,
    model: str,
    system: str | list[dict[str, Any]],
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    execute: ToolExecutor,
    max_iterations: int = MAX_ITERATIONS,
    deadline_s: float = DEADLINE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> LoopResult:
    """Drive Claude until it answers, refuses, or a cap is hit. ``messages`` is mutated."""
    start = clock()
    result = LoopResult(reply="", model=model, stop_reason=None, iterations=0)
    last_text = ""

    for _ in range(max_iterations):
        remaining = deadline_s - (clock() - start)
        if remaining < _MIN_CALL_BUDGET:
            result.reply = _with_note(last_text, "I ran out of time on that one — ask me again.")
            return result
        result.iterations += 1
        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=system,
                    tools=tools,
                    tool_choice={"type": "auto"},
                    messages=messages,
                ),
                timeout=remaining,
            )
        except TimeoutError:
            result.reply = _with_note(last_text, "I ran out of time on that one — ask me again.")
            return result
        except anthropic.AuthenticationError as exc:
            raise AssistantUnavailableError(
                "The assistant's Anthropic API key was rejected. Check ANTHROPIC_API_KEY."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise AssistantUnavailableError(
                "The assistant is rate-limited right now. Try again in a minute.", 429
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise AssistantUnavailableError("Couldn't reach the assistant's model.") from exc
        except anthropic.APIStatusError as exc:
            logger.warning("assistant.api_status_error", status=exc.status_code)
            raise AssistantUnavailableError(
                f"The assistant's model returned an error ({exc.status_code}).", 502
            ) from exc

        result.stop_reason = response.stop_reason
        content = list(response.content)

        if response.stop_reason == "refusal":
            result.reply = (
                "I can't help with that request. I can search your jobs, check a résumé, "
                "review applications or run your agents."
            )
            return result

        text = _text_of(content)
        last_text = text or last_text
        if response.stop_reason == "max_tokens":
            result.reply = _with_note(text or last_text, "My reply was cut short.")
            return result

        # Full content, thinking blocks and all, goes back unchanged.
        messages.append({"role": "assistant", "content": content})

        tool_uses = [b for b in content if getattr(b, "type", None) == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            result.reply = text or "Done."
            return result

        results: list[dict[str, Any]] = []
        for block in tool_uses:
            outcome = await _safe_execute(execute, block.name, block.input)
            result.tool_calls.append(
                ToolCallRecord(
                    name=block.name,
                    input_summary=_input_summary(block.input),
                    ok=outcome.ok,
                    result_summary=outcome.summary[:200],
                )
            )
            if outcome.pending:
                result.pending.append(outcome.pending)
            entry: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": outcome.content,
            }
            if not outcome.ok:
                entry["is_error"] = True
            results.append(entry)
        # One user message carrying every result of this turn.
        messages.append({"role": "user", "content": results})

    result.reply = _with_note(
        last_text, f"I paused after {max_iterations} steps. Say 'continue' to keep going."
    )
    return result


async def _safe_execute(execute: ToolExecutor, name: str, raw: Any) -> ToolOutcome:
    try:
        return await execute(name, raw)
    except Exception as exc:  # a tool failure is reported to Claude, never crashes the chat
        logger.warning("assistant.tool_failed", tool=name, error=type(exc).__name__)
        return ToolOutcome(ok=False, content=f"Tool failed: {exc}"[:500], summary="failed")


def _with_note(text: str, note: str) -> str:
    return f"{text}\n\n{note}".strip() if text else note
