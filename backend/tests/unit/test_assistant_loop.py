"""Assistant tool-use loop + confirmation tokens, against a mocked AsyncAnthropic."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from anthropic.types import TextBlock, ThinkingBlock, ToolUseBlock

from app.core.assistant import tokens
from app.core.assistant import tools as t
from app.core.assistant.context import ToolContext
from app.core.assistant.executor import make_executor
from app.core.assistant.loop import (
    AssistantUnavailableError,
    ToolOutcome,
    run_loop,
)


def _msg(stop: str, *blocks: Any) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


def _tool(i: str, name: str, inp: dict) -> ToolUseBlock:
    return ToolUseBlock(type="tool_use", id=i, name=name, input=inp)


def _text(s: str) -> TextBlock:
    return TextBlock(type="text", text=s)


THINK = ThinkingBlock(type="thinking", thinking="", signature="sig-abc")


class FakeClient:
    """Records a deep copy of ``messages`` per call (the loop mutates the same list)."""

    def __init__(self, responses: list[Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs: Any) -> Any:
        self.calls.append({**kwargs, "messages": copy.copy(kwargs["messages"])})
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


async def _ok_exec(name: str, raw: Any) -> ToolOutcome:
    return ToolOutcome(ok=True, content=f'{{"tool":"{name}"}}', summary=f"{name} ok")


def _run(client: FakeClient, execute: Any = _ok_exec, **kw: Any):
    return run_loop(
        client,
        model="claude-sonnet-5-5",
        system="sys",
        tools=t.definitions(),
        messages=[{"role": "user", "content": "hi"}],
        execute=execute,
        **kw,
    )


class TestLoop:
    async def test_appends_full_content_including_thinking(self):
        first = _msg("tool_use", THINK, _text("Looking."), _tool("tu1", "get_overview", {}))
        client = FakeClient([first, _msg("end_turn", _text("All good."))])
        result = await _run(client)

        assert result.reply == "All good."
        second_call = client.calls[1]["messages"]
        assistant_turn = second_call[1]
        assert assistant_turn["role"] == "assistant"
        # The exact block objects, thinking first, unchanged.
        assert assistant_turn["content"] == first.content
        assert assistant_turn["content"][0] is THINK

    async def test_request_shape(self):
        client = FakeClient([_msg("end_turn", _text("Hi."))])
        await _run(client)
        call = client.calls[0]
        assert call["tool_choice"] == {"type": "auto"}
        assert call["max_tokens"] == 16000
        assert "temperature" not in call
        assert all(d["input_schema"]["additionalProperties"] is False for d in call["tools"])

    async def test_tool_results_batched_in_one_user_message(self):
        first = _msg(
            "tool_use",
            _tool("a", "get_overview", {}),
            _tool("b", "list_agents", {}),
            _tool("c", "nope", {}),
        )
        client = FakeClient([first, _msg("end_turn", _text("Done."))])

        async def execute(name: str, raw: Any) -> ToolOutcome:
            if name == "nope":
                raise RuntimeError("boom")
            return await _ok_exec(name, raw)

        result = await _run(client, execute)
        msgs = client.calls[1]["messages"]
        assert len(msgs) == 3
        results = msgs[2]
        assert results["role"] == "user"
        assert [r["tool_use_id"] for r in results["content"]] == ["a", "b", "c"]
        assert all(r["type"] == "tool_result" for r in results["content"])
        assert results["content"][2]["is_error"] is True
        assert "is_error" not in results["content"][0]
        assert [c.ok for c in result.tool_calls] == [True, True, False]

    async def test_refusal_is_handled(self):
        client = FakeClient([_msg("refusal", _text("partial"))])
        result = await _run(client)
        assert result.stop_reason == "refusal"
        assert "can't help" in result.reply
        assert "partial" not in result.reply

    async def test_max_tokens_does_not_run_tools(self):
        executed: list[str] = []

        async def execute(name: str, raw: Any) -> ToolOutcome:
            executed.append(name)
            return await _ok_exec(name, raw)

        client = FakeClient([_msg("max_tokens", _text("Half"), _tool("x", "get_overview", {}))])
        result = await _run(client, execute)
        assert executed == []
        assert "cut short" in result.reply

    async def test_iteration_cap(self):
        looping = [_msg("tool_use", _tool(f"t{i}", "get_overview", {})) for i in range(10)]
        client = FakeClient(looping)
        result = await _run(client, max_iterations=3)
        assert len(client.calls) == 3
        assert result.iterations == 3
        assert "paused after 3 steps" in result.reply

    async def test_deadline_stops_before_calling(self):
        ticks = iter([0.0, 100.0])
        client = FakeClient([_msg("end_turn", _text("never"))])
        result = await _run(client, clock=lambda: next(ticks))
        assert client.calls == []
        assert "ran out of time" in result.reply

    async def test_typed_sdk_errors_map_to_unavailable(self):
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        err = anthropic.RateLimitError(
            "slow down", response=httpx.Response(429, request=req), body=None
        )
        with pytest.raises(AssistantUnavailableError) as info:
            await _run(FakeClient([err]))
        assert info.value.status_code == 429

        conn = anthropic.APIConnectionError(request=req)
        with pytest.raises(AssistantUnavailableError):
            await _run(FakeClient([conn]))


class TestValidation:
    async def test_bad_input_rejected_before_handler(self):
        execute = make_executor(ToolContext(db=AsyncMock(), user_id="u1"))
        out = await execute("search_stored_jobs", {"limit": 500})
        assert out.ok is False and "Invalid input" in out.content
        out = await execute("get_overview", {"surprise": 1})
        assert out.ok is False and "Invalid input" in out.content
        out = await execute("approve_applications", {"application_ids": []})
        assert out.ok is False
        out = await execute("drop_tables", {})
        assert out.ok is False and "Unknown tool" in out.content


class TestTokens:
    def test_round_trip(self):
        tok = tokens.issue("user-a", "stage_application", {"job_id": "j1"})
        pending = tokens.verify(tok, "user-a")
        assert pending.action == "stage_application" and pending.params == {"job_id": "j1"}

    def test_forged_signature_rejected(self):
        tok = tokens.issue("user-a", "stage_application", {"job_id": "j1"})
        body, sig = tok.split(".")
        forged_body = tokens._b64(
            tokens._unb64(body).replace(b'"j1"', b'"j2"')
        )
        with pytest.raises(tokens.TokenError):
            tokens.verify(f"{forged_body}.{sig}", "user-a")
        with pytest.raises(tokens.TokenError):
            tokens.verify(f"{body}.{sig[:-2]}xx", "user-a")
        with pytest.raises(tokens.TokenError):
            tokens.verify("not-a-token", "user-a")

    def test_expired_rejected(self):
        tok = tokens.issue("user-a", "run_discovery_now", {}, now=1_000)
        with pytest.raises(tokens.TokenError, match="expired"):
            tokens.verify(tok, "user-a", now=1_000 + tokens.TOKEN_TTL_SECONDS + 1)

    def test_other_users_token_rejected(self):
        tok = tokens.issue("user-a", "run_discovery_now", {})
        with pytest.raises(tokens.TokenError):
            tokens.verify(tok, "user-b")

    async def test_claim_once(self):
        pending = tokens.verify(tokens.issue("user-a", "run_discovery_now", {}), "user-a")
        assert await tokens.claim_once(pending, None) is True
        assert await tokens.claim_once(pending, None) is False
