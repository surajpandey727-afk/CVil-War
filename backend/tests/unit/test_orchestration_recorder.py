"""Unit tests for core.orchestration.recorder — the shared agent-run instrumentation.

Covers the honesty properties every agent's audit trail depends on: a run always ends up
closed (never stuck at RUNNING), a raised exception is recorded as an error and re-raised
unchanged, and a node that sets its own terminal status (e.g. NEEDS_REVIEW) before returning
normally is respected rather than clobbered by the default DONE.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.orchestration.recorder import record_agent_run
from app.models.agent_run import AgentRun
from app.models.enums import AgentName, AgentRunStatus
from tests.conftest import TEST_USER_ID


async def _only_run(db_session) -> AgentRun:
    rows = (await db_session.execute(select(AgentRun))).scalars().all()
    assert len(rows) == 1
    return rows[0]


class TestRecordAgentRun:
    async def test_success_path_writes_done(self, db_session) -> None:
        async with record_agent_run(
            db_session, TEST_USER_ID, AgentName.ELIGIBILITY, input_summary="check sponsor",
        ) as run:
            run.output_summary = "confirmed"

        row = await _only_run(db_session)
        assert row.status == AgentRunStatus.DONE
        assert row.output_summary == "confirmed"
        assert row.finished_at is not None
        assert row.input_summary == "check sponsor"

    async def test_exception_writes_error_and_reraises(self, db_session) -> None:
        with pytest.raises(ValueError, match="boom"):
            async with record_agent_run(db_session, TEST_USER_ID, AgentName.SCORING):
                raise ValueError("boom")

        row = await _only_run(db_session)
        assert row.status == AgentRunStatus.ERROR
        assert "boom" in row.error
        assert row.finished_at is not None

    async def test_cancelled_error_still_closes_the_row(self, db_session) -> None:
        import asyncio

        with pytest.raises(asyncio.CancelledError):
            async with record_agent_run(db_session, TEST_USER_ID, AgentName.APPLICATION):
                raise asyncio.CancelledError()

        row = await _only_run(db_session)
        assert row.status == AgentRunStatus.ERROR
        assert row.finished_at is not None

    async def test_caller_set_terminal_status_is_respected(self, db_session) -> None:
        async with record_agent_run(db_session, TEST_USER_ID, AgentName.APPLICATION) as run:
            run.status = AgentRunStatus.NEEDS_REVIEW
            run.output_summary = "blocked on captcha"

        row = await _only_run(db_session)
        assert row.status == AgentRunStatus.NEEDS_REVIEW
        assert row.finished_at is not None

    async def test_linked_entity_is_persisted(self, db_session) -> None:
        async with record_agent_run(
            db_session, TEST_USER_ID, AgentName.SCORING,
            linked_entity_type="job", linked_entity_id="job-123",
        ):
            pass

        row = await _only_run(db_session)
        assert row.linked_entity_type == "job"
        assert row.linked_entity_id == "job-123"

    async def test_publish_failure_never_breaks_the_agent(self, db_session) -> None:
        """A dead WS bus must not fail the agent it is reporting on."""

        class _ExplodingRedis:
            pass

        async with record_agent_run(
            db_session, TEST_USER_ID, AgentName.DISCOVERY, redis=_ExplodingRedis(),
        ) as run:
            run.output_summary = "ok despite bad redis"

        row = await _only_run(db_session)
        assert row.status == AgentRunStatus.DONE
        assert row.output_summary == "ok despite bad redis"
