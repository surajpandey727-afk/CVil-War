"""The pre-submit confirmation gate: approve/reject/timeout paths, and the stop-callback
that turns a rejection into the run actually ending.

Mirrors ``test_phase2_backbone.py::TestInterventionRendezvous`` — same fakeredis rendezvous,
just the "approved"/anything-else meaning instead of a typed 2FA code.
"""

import fakeredis.aioredis

from app.core.automation.intervention import resolve_intervention
from app.core.automation.runtime.confirmation import (
    ConfirmationOutcome,
    SubmissionApprovalParams,
    build_confirmation_tools,
    make_should_stop_callback,
)


class _FakeBrowserSession:
    """Stands in for browser_use's BrowserSession — only the two methods the action calls."""

    def __init__(self, url: str = "https://example.com/apply", screenshot: bytes = b"\x89PNG") -> None:
        self._url = url
        self._screenshot = screenshot

    async def get_current_page_url(self) -> str:
        return self._url

    async def take_screenshot(self) -> bytes:
        return self._screenshot


def _registered_action(tools):
    return tools.registry.registry.actions["request_submission_approval"].function


class TestBuildConfirmationTools:
    async def test_approved_returns_success_and_leaves_outcome_unrejected(self):
        redis = fakeredis.aioredis.FakeRedis()
        outcome = ConfirmationOutcome()
        tools = build_confirmation_tools(
            redis=redis, user_id="u1", application_id="app-1", company="Acme", outcome=outcome,
        )
        action = _registered_action(tools)
        await resolve_intervention(redis, "app-1", "approved")

        result = await action(
            params=SubmissionApprovalParams(summary="Applying to Acme as a Data Analyst"),
            browser_session=_FakeBrowserSession(),
        )

        assert outcome.rejected is False
        assert result.error is None
        assert "Approved" in (result.extracted_content or "")

    async def test_rejected_sets_outcome_and_returns_error(self):
        redis = fakeredis.aioredis.FakeRedis()
        outcome = ConfirmationOutcome()
        tools = build_confirmation_tools(
            redis=redis, user_id="u1", application_id="app-2", company="Acme", outcome=outcome,
        )
        action = _registered_action(tools)
        await resolve_intervention(redis, "app-2", "rejected")

        result = await action(
            params=SubmissionApprovalParams(summary="Applying to Acme"),
            browser_session=_FakeBrowserSession(),
        )

        assert outcome.rejected is True
        assert outcome.reason == "The operator did not approve this submission."
        assert result.error == outcome.reason

    async def test_timeout_sets_outcome_rejected(self, monkeypatch):
        redis = fakeredis.aioredis.FakeRedis()
        outcome = ConfirmationOutcome()
        tools = build_confirmation_tools(
            redis=redis, user_id="u1", application_id="app-3", company="Acme", outcome=outcome,
        )
        action = _registered_action(tools)

        async def _never_responds(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "app.core.automation.runtime.confirmation.request_intervention", _never_responds
        )

        result = await action(
            params=SubmissionApprovalParams(summary="Applying to Acme"),
            browser_session=_FakeBrowserSession(),
        )

        assert outcome.rejected is True
        assert "No response within" in outcome.reason
        assert result.error == outcome.reason

    async def test_no_redis_fails_closed_without_submitting(self):
        outcome = ConfirmationOutcome()
        tools = build_confirmation_tools(
            redis=None, user_id="u1", application_id="app-4", company="Acme", outcome=outcome,
        )
        action = _registered_action(tools)

        result = await action(
            params=SubmissionApprovalParams(summary="Applying to Acme"),
            browser_session=_FakeBrowserSession(),
        )

        assert outcome.rejected is True
        assert "No live connection" in outcome.reason
        assert result.error == outcome.reason

    async def test_a_failed_screenshot_does_not_block_the_request(self):
        redis = fakeredis.aioredis.FakeRedis()
        outcome = ConfirmationOutcome()
        tools = build_confirmation_tools(
            redis=redis, user_id="u1", application_id="app-5", company="Acme", outcome=outcome,
        )
        action = _registered_action(tools)
        await resolve_intervention(redis, "app-5", "approved")

        class _BrokenScreenshotSession(_FakeBrowserSession):
            async def take_screenshot(self) -> bytes:
                raise RuntimeError("no display")

        result = await action(
            params=SubmissionApprovalParams(summary="Applying to Acme"),
            browser_session=_BrokenScreenshotSession(),
        )

        assert outcome.rejected is False
        assert result.error is None


class TestShouldStopCallback:
    async def test_reflects_outcome_rejected(self):
        outcome = ConfirmationOutcome()
        should_stop = make_should_stop_callback(outcome)

        assert await should_stop() is False
        outcome.rejected = True
        assert await should_stop() is True
