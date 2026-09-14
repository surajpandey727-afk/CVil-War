"""Integration tests for GET /api/v1/agent-runs — the Agent Ops surface."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.agent_run import AgentRun
from app.models.enums import AgentName, AgentRunStatus
from tests.conftest import TEST_USER_ID

API_PREFIX = "/api/v1/agent-runs"


async def _make_run(
    db_session, agent_name: AgentName, status: AgentRunStatus, **kwargs,
) -> AgentRun:
    run = AgentRun(
        user_id=TEST_USER_ID,
        agent_name=agent_name,
        status=status,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        **kwargs,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


class TestListAgentRuns:
    async def test_empty_history_still_returns_all_five_nodes(self, client) -> None:
        response = await client.get(f"{API_PREFIX}/")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert {n["agent_name"] for n in body["nodes"]} == {a.value for a in AgentName}
        assert all(n["last_run"] is None for n in body["nodes"])

    async def test_lists_runs_most_recent_first(self, db_session, client) -> None:
        await _make_run(
            db_session, AgentName.DISCOVERY, AgentRunStatus.DONE, output_summary="first",
        )
        await _make_run(
            db_session, AgentName.DISCOVERY, AgentRunStatus.DONE, output_summary="second",
        )

        response = await client.get(f"{API_PREFIX}/")

        body = response.json()
        assert body["total"] == 2
        assert [i["output_summary"] for i in body["items"]] == ["second", "first"]

    async def test_filters_by_agent_name(self, db_session, client) -> None:
        await _make_run(db_session, AgentName.DISCOVERY, AgentRunStatus.DONE)
        await _make_run(db_session, AgentName.APPLICATION, AgentRunStatus.ERROR)

        response = await client.get(f"{API_PREFIX}/", params={"agent_name": "application"})

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["agent_name"] == "application"

    async def test_filters_by_status(self, db_session, client) -> None:
        await _make_run(db_session, AgentName.SCORING, AgentRunStatus.DONE)
        await _make_run(db_session, AgentName.SCORING, AgentRunStatus.ERROR)

        response = await client.get(f"{API_PREFIX}/", params={"status": "error"})

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "error"

    async def test_filters_by_linked_entity(self, db_session, client) -> None:
        await _make_run(
            db_session, AgentName.ELIGIBILITY, AgentRunStatus.DONE,
            linked_entity_type="job", linked_entity_id="job-abc",
        )
        await _make_run(
            db_session, AgentName.ELIGIBILITY, AgentRunStatus.DONE,
            linked_entity_type="job", linked_entity_id="job-xyz",
        )

        response = await client.get(
            f"{API_PREFIX}/", params={"linked_entity_type": "job", "linked_entity_id": "job-abc"},
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["linked_entity_id"] == "job-abc"

    async def test_node_reflects_latest_run_per_agent_regardless_of_filters(
        self, db_session, client,
    ) -> None:
        await _make_run(
            db_session, AgentName.DISCOVERY, AgentRunStatus.ERROR, output_summary="old failure",
        )
        await _make_run(
            db_session, AgentName.DISCOVERY, AgentRunStatus.DONE, output_summary="latest ok",
        )

        response = await client.get(f"{API_PREFIX}/", params={"status": "error"})

        body = response.json()
        assert body["total"] == 1  # the filtered log only shows the error row
        node = next(n for n in body["nodes"] if n["agent_name"] == "discovery")
        assert node["status"] == "done"  # but the node reflects the true latest state
        assert node["last_run"]["output_summary"] == "latest ok"

    async def test_pagination(self, db_session, client) -> None:
        for i in range(3):
            await _make_run(
                db_session, AgentName.TRACKING, AgentRunStatus.DONE, output_summary=str(i),
            )

        response = await client.get(f"{API_PREFIX}/", params={"page": 1, "page_size": 2})

        body = response.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2

    async def test_requires_authentication(self, anon_client) -> None:
        response = await anon_client.get(f"{API_PREFIX}/")
        assert response.status_code in (401, 403)
