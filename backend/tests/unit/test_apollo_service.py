"""Unit tests for services.apollo — logging a recruiter contact into Apollo.

httpx is fully mocked (via ``httpx.MockTransport``); no real network call is ever made.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.services import apollo

_RealAsyncClient = httpx.AsyncClient


def _fake_settings(api_key: str) -> SimpleNamespace:
    return SimpleNamespace(apollo_api_key=SimpleNamespace(get_secret_value=lambda: api_key))


def _mock_transport(monkeypatch, handler) -> None:
    """Route every ``httpx.AsyncClient(...)`` apollo.py constructs through ``handler``,
    without recursing into the patched constructor itself."""
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: _RealAsyncClient(transport=httpx.MockTransport(handler), **kw),
    )


@pytest.fixture(autouse=True)
def _apollo_key(monkeypatch):
    """Every test gets a configured key by default; individual tests override to unset it."""
    monkeypatch.setattr(apollo, "get_settings", lambda: _fake_settings("test-key"))
    yield


class TestLogContact:
    async def test_raises_when_not_configured(self, monkeypatch) -> None:
        monkeypatch.setattr(apollo, "get_settings", lambda: _fake_settings(""))
        with pytest.raises(apollo.ApolloNotConfiguredError):
            await apollo.log_contact(email="x@y.com")

    async def test_creates_a_new_contact(self, monkeypatch) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={"contact": {"id": "abc123", "contact_emails": []}})

        _mock_transport(monkeypatch, handler)

        result = await apollo.log_contact(
            email="recruiter@acme.com", first_name="Jane", last_name="Doe",
            organization_name="Acme", title="Recruiter",
        )

        assert result.contact_id == "abc123"
        assert result.matched_existing is False
        assert captured["url"] == "https://api.apollo.io/v1/contacts"
        assert captured["headers"]["x-api-key"] == "test-key"

    async def test_flags_an_existing_contact_as_matched(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"contact": {"id": "abc123", "contact_emails": [{"email": "x@y.com"}]}},
            )

        _mock_transport(monkeypatch, handler)

        result = await apollo.log_contact(email="x@y.com")
        assert result.matched_existing is True

    async def test_reraises_on_http_error(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "invalid api key"})

        _mock_transport(monkeypatch, handler)

        with pytest.raises(httpx.HTTPStatusError):
            await apollo.log_contact(email="x@y.com")
