"""Assistant + AI Agents routes through the HTTP stack (Anthropic client mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from anthropic.types import TextBlock, ToolUseBlock
from sqlalchemy import select

from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.services import assistant as service


class _Client:
    def __init__(self, responses: list[Any]) -> None:
        self.kwargs: list[dict[str, Any]] = []
        self._responses = responses
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs: Any) -> Any:
        self.kwargs.append(kwargs)
        return self._responses.pop(0)


def _msg(stop: str, *blocks: Any) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


def _install(monkeypatch, responses: list[Any]) -> _Client:
    client = _Client(responses)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(service, "get_client", lambda: client)
    return client


async def _job(db, data: dict) -> Job:
    job = Job(**data)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def test_missing_key_is_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = await client.post(
        "/api/v1/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


async def test_requires_auth(anon_client):
    resp = await anon_client.post(
        "/api/v1/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 401
    assert (await anon_client.get("/api/v1/assistant/agents")).status_code == 401


async def test_chat_runs_read_tool(client, monkeypatch, db_session, sample_job_data):
    await _job(db_session, sample_job_data)
    fake = _install(
        monkeypatch,
        [
            _msg("tool_use", ToolUseBlock(type="tool_use", id="t1", name="get_overview", input={})),
            _msg("end_turn", TextBlock(type="text", text="You have 1 UK job.")),
        ],
    )
    resp = await client.post(
        "/api/v1/assistant/chat",
        json={"messages": [{"role": "user", "content": "What's going on?"}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"] == "You have 1 UK job."
    assert body["model"] == "claude-sonnet-5-5"
    assert body["tool_calls"][0]["name"] == "get_overview" and body["tool_calls"][0]["ok"]
    assert body["pending"] == []
    tool_result = fake.kwargs[1]["messages"][2]["content"][0]
    assert '"uk_jobs":1' in tool_result["content"]
    assert "test-key-not-real" not in resp.text


async def test_stage_then_confirm(client, monkeypatch, db_session, sample_job_data):
    job = await _job(db_session, sample_job_data)
    _install(
        monkeypatch,
        [
            _msg(
                "tool_use",
                ToolUseBlock(
                    type="tool_use", id="t1", name="stage_application", input={"job_id": job.id}
                ),
            ),
            _msg("end_turn", TextBlock(type="text", text="Press Confirm to stage it.")),
        ],
    )
    resp = await client.post(
        "/api/v1/assistant/chat",
        json={"messages": [{"role": "user", "content": "Apply to the Python job"}]},
    )
    body = resp.json()
    assert len(body["pending"]) == 1
    assert (await db_session.execute(select(Application))).scalars().all() == []

    token = body["pending"][0]["token"]
    confirmed = await client.post("/api/v1/assistant/confirm", json={"token": token})
    assert confirmed.status_code == 200 and confirmed.json()["ok"], confirmed.text
    (app,) = (await db_session.execute(select(Application))).scalars().all()
    assert app.status == ApplicationStatus.PENDING_REVIEW

    forged = await client.post("/api/v1/assistant/confirm", json={"token": token[:-3] + "abc"})
    assert forged.json()["ok"] is False


async def test_history_must_end_with_user(client, monkeypatch):
    _install(monkeypatch, [])
    resp = await client.post(
        "/api/v1/assistant/chat",
        json={
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ]
        },
    )
    assert resp.status_code == 422


async def test_history_capped(client, monkeypatch):
    _install(monkeypatch, [])
    messages = [{"role": "user", "content": "x"}] * 21
    resp = await client.post("/api/v1/assistant/chat", json={"messages": messages})
    assert resp.status_code == 422


async def test_agents_roster(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = await client.get("/api/v1/assistant/agents")
    assert resp.status_code == 200
    body = resp.json()
    keys = [a["key"] for a in body["agents"]]
    assert keys == [
        "discovery",
        "eligibility",
        "scoring",
        "resume",
        "application",
        "tracking",
        "assistant",
    ]
    assistant = body["agents"][-1]
    assert assistant["status"] == "off" and "ANTHROPIC_API_KEY" in assistant["status_text"]
    assert body["assistant_available"] is False
    application = next(a for a in body["agents"] if a["key"] == "application")
    assert "Live apply is off" in application["status_text"]
    for agent in body["agents"]:
        assert agent["section"]["to"].startswith("/")


async def test_prepare_discovery_without_targets(client):
    resp = await client.post("/api/v1/assistant/prepare", json={"action": "run_discovery_now"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False and resp.json()["pending"] is None
