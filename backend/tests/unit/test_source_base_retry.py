"""Retry/backoff/jitter for `ApiJobSource._fetch_with_retry`.

No API source had any retry logic at all before this: a single 429/503 or a dropped
connection ended the whole fetch immediately, indistinguishable from the source being
genuinely dead. These tests exercise the retry wrapper directly against a minimal fake
adapter, with `asyncio.sleep` patched so a real backoff delay never slows the suite.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.automation.platforms.base import JobListing
from app.core.job_discovery.sources import base as base_module
from app.core.job_discovery.sources.base import ApiJobSource


class _FakeSource(ApiJobSource):
    source_name = "fake"

    def __init__(self, fetch: AsyncMock) -> None:
        super().__init__()
        self._fetch_mock = fetch

    async def _fetch(self, client, query, location, limit):
        return await self._fetch_mock(client, query, location, limit)

    def _to_listing(self, record):
        return JobListing(
            platform="fake", platform_job_id=record["id"], title=record["title"],
            company="Acme", location="London", url="https://example.com",
            description="",
        )


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


@pytest.fixture(autouse=True)
def _no_real_sleep():
    with patch.object(base_module.asyncio, "sleep", new=AsyncMock()) as sleep:
        yield sleep


class TestFetchWithRetry:
    async def test_succeeds_on_the_first_try_with_no_retry(self, _no_real_sleep):
        fetch = AsyncMock(return_value=[{"id": "1", "title": "Eng"}])
        source = _FakeSource(fetch)
        result = await source._fetch_with_retry(None, "q", "", 10)
        assert result == [{"id": "1", "title": "Eng"}]
        assert fetch.await_count == 1
        _no_real_sleep.assert_not_awaited()

    async def test_retries_a_429_and_eventually_succeeds(self, _no_real_sleep):
        fetch = AsyncMock(
            side_effect=[_status_error(429), [{"id": "1", "title": "Eng"}]],
        )
        source = _FakeSource(fetch)
        result = await source._fetch_with_retry(None, "q", "", 10)
        assert result == [{"id": "1", "title": "Eng"}]
        assert fetch.await_count == 2
        _no_real_sleep.assert_awaited_once()

    async def test_retries_a_503_and_a_timeout_before_succeeding(self, _no_real_sleep):
        fetch = AsyncMock(
            side_effect=[
                _status_error(503),
                httpx.TimeoutException("slow"),
                [{"id": "1", "title": "Eng"}],
            ],
        )
        source = _FakeSource(fetch)
        result = await source._fetch_with_retry(None, "q", "", 10)
        assert result == [{"id": "1", "title": "Eng"}]
        assert fetch.await_count == 3

    async def test_gives_up_after_exhausting_retries_and_raises(self, _no_real_sleep):
        fetch = AsyncMock(side_effect=_status_error(429))
        source = _FakeSource(fetch)
        with pytest.raises(httpx.HTTPStatusError):
            await source._fetch_with_retry(None, "q", "", 10)
        # MAX_FETCH_RETRIES=2 -> 3 total attempts (the original + 2 retries).
        assert fetch.await_count == base_module.MAX_FETCH_RETRIES + 1

    async def test_a_non_retryable_status_is_not_retried_at_all(self, _no_real_sleep):
        """401/403/404 will not succeed on replay — retrying just wastes quota and time."""
        fetch = AsyncMock(side_effect=_status_error(403))
        source = _FakeSource(fetch)
        with pytest.raises(httpx.HTTPStatusError):
            await source._fetch_with_retry(None, "q", "", 10)
        assert fetch.await_count == 1
        _no_real_sleep.assert_not_awaited()

    async def test_search_still_degrades_to_empty_after_retries_are_exhausted(
        self, _no_real_sleep,
    ):
        """The end-to-end contract search() already promised — never raise, degrade to []
        — must survive adding retries underneath it."""
        fetch = AsyncMock(side_effect=_status_error(503))
        source = _FakeSource(fetch)
        result = await source.search("python developer")
        assert result == []
        assert fetch.await_count == base_module.MAX_FETCH_RETRIES + 1
