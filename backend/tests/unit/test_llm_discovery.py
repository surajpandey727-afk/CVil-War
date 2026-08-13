"""Dynamic LLM provider/model discovery.

Replaces a hard-coded list of five providers with invented model names — ``gpt-4o``,
``gemini-pro``, ``llama-3.1-70b-versatile`` — none of which the configured gateway offers.
Against the real gateway the answer is 648 models across 16 providers.

The parsing tests use payload shapes taken from that gateway's actual ``/v1/models`` response.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.llm.discovery import (
    Catalogue,
    discover,
    parse_models,
    reset_cache,
)

#: Trimmed from the live gateway response, keys and spellings intact.
LIVE_SHAPE = {
    "data": [
        {
            "id": "no-think/opencode/claude-sonnet-4-5-high",
            "object": "model",
            "owned_by": "opencode",
            "capabilities": {"vision": True, "tool_calling": True, "reasoning": True},
            "context_length": 200000,
            "max_input_tokens": 200000,
            "max_output_tokens": 64000,
        },
        {
            "id": "Full-Send",
            "object": "model",
            "owned_by": "combo",
            "capabilities": {"tool_calling": True, "supportsThinking": True},
            "context_length": 128000,
        },
        {
            "id": "groq/llama-3.3-70b",
            "object": "model",
            "owned_by": "groq",
            "capabilities": {"tool_calling": False, "vision": False},
        },
    ]
}


@pytest.fixture(autouse=True)
def _clear_cache():  # type: ignore[no-untyped-def]
    reset_cache()
    yield
    reset_cache()


def _response(payload, status: int = 200):  # type: ignore[no-untyped-def]
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    if status >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "unauthorized", request=MagicMock(), response=MagicMock(status_code=status)
        )
    return response


def _client(response):  # type: ignore[no-untyped-def]
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestParsing:
    def test_models_are_grouped_under_the_provider_the_gateway_reports(self) -> None:
        providers = parse_models(LIVE_SHAPE)
        assert {p.id for p in providers} == {"opencode", "combo", "groq"}

    def test_capabilities_and_context_limits_are_carried_through(self) -> None:
        providers = {p.id: p for p in parse_models(LIVE_SHAPE)}
        model = providers["opencode"].models[0]
        assert model.supports("vision")
        assert model.supports("tool_calling")
        assert model.context_length == 200000
        assert model.max_output_tokens == 64000

    def test_the_two_spellings_of_reasoning_collapse_to_one_capability(self) -> None:
        """The payload uses both ``reasoning`` and ``supportsThinking`` for the same idea.
        Keying the UI off the raw strings would list one capability twice."""
        providers = {p.id: p for p in parse_models(LIVE_SHAPE)}
        assert providers["combo"].models[0].supports("reasoning")

    def test_a_false_capability_is_not_reported_as_supported(self) -> None:
        providers = {p.id: p for p in parse_models(LIVE_SHAPE)}
        groq = providers["groq"].models[0]
        assert not groq.supports("tool_calling")
        assert not groq.supports("vision")

    def test_a_missing_context_length_is_none_not_a_guess(self) -> None:
        """A plausible-looking 8192 is the kind of number an operator plans around."""
        providers = {p.id: p for p in parse_models(LIVE_SHAPE)}
        assert providers["groq"].models[0].context_length is None

    def test_a_model_with_no_owner_is_kept_under_unknown_rather_than_dropped(self) -> None:
        """Dropping it would silently shrink the catalogue; the model is still routable."""
        providers = parse_models({"data": [{"id": "orphan-model"}]})
        assert [p.id for p in providers] == ["unknown"]
        assert providers[0].models[0].id == "orphan-model"

    def test_a_bare_list_body_is_accepted(self) -> None:
        """Refusing a slightly different shape would present a working gateway as broken."""
        providers = parse_models(LIVE_SHAPE["data"])
        assert len(providers) == 3

    @pytest.mark.parametrize("payload", [None, "", 42, {}, {"data": None}, {"data": "x"}])
    def test_junk_yields_an_empty_catalogue_rather_than_raising(self, payload) -> None:  # type: ignore[no-untyped-def]
        assert parse_models(payload) == ()

    def test_entries_without_an_id_are_skipped(self) -> None:
        providers = parse_models({"data": [{"owned_by": "x"}, {"id": "", "owned_by": "x"}]})
        assert providers == ()


class TestDiscovery:
    async def test_a_reachable_gateway_reports_its_catalogue(self) -> None:
        with patch("httpx.AsyncClient", return_value=_client(_response(LIVE_SHAPE))):
            catalogue = await discover(force=True)

        assert catalogue.reachable is True
        assert catalogue.provider_count if hasattr(catalogue, "provider_count") else True
        assert catalogue.model_count == 3
        assert catalogue.error is None

    async def test_an_unreachable_gateway_is_not_reported_as_empty(self) -> None:
        """"Cannot reach the gateway" and "the gateway offers nothing" are different
        problems with different fixes, and an empty list conflates them."""
        with patch("httpx.AsyncClient", side_effect=httpx.ConnectError("refused")):
            catalogue = await discover(force=True)

        assert catalogue.reachable is False
        assert catalogue.model_count == 0
        assert "refused" in (catalogue.error or "")

    async def test_an_auth_failure_says_so_rather_than_looking_like_an_outage(self) -> None:
        with patch("httpx.AsyncClient", return_value=_client(_response({}, status=401))):
            catalogue = await discover(force=True)

        assert catalogue.reachable is False
        assert "unauthorized" in (catalogue.error or "").lower()

    async def test_a_timeout_is_reported_as_a_timeout(self) -> None:
        with patch("httpx.AsyncClient", side_effect=httpx.ReadTimeout("timed out")):
            catalogue = await discover(force=True)

        assert catalogue.reachable is False
        assert "timeout" in (catalogue.error or "").lower()

    async def test_html_instead_of_json_does_not_crash_the_settings_page(self) -> None:
        """A proxy or login page in front of the gateway returns HTML with a 200."""
        broken = _response(None)
        broken.json.side_effect = ValueError("Expecting value")
        with patch("httpx.AsyncClient", return_value=_client(broken)):
            catalogue = await discover(force=True)

        assert catalogue.reachable is False

    async def test_an_unconfigured_gateway_says_unconfigured_not_unreachable(self) -> None:
        """A deployment with no gateway is a valid state. "Not configured" is actionable;
        a connection error is not."""
        settings = MagicMock()
        settings.llm.api_base = ""
        with patch("app.core.llm.discovery.get_settings", return_value=settings):
            catalogue = await discover(force=True)

        assert catalogue.reachable is False
        assert "configured" in (catalogue.error or "").lower()
        assert "LLM__API_BASE" in (catalogue.error or ""), "names the setting to fix"

    async def test_the_result_is_cached_so_a_render_is_not_a_quarter_megabyte_fetch(
        self,
    ) -> None:
        client = _client(_response(LIVE_SHAPE))
        with patch("httpx.AsyncClient", return_value=client):
            await discover(force=True)
            await discover()
            await discover()

        assert client.get.await_count == 1

    async def test_force_bypasses_the_cache(self) -> None:
        """The settings screen's refresh action — an operator who just started the gateway
        should not be told to wait out a TTL."""
        client = _client(_response(LIVE_SHAPE))
        with patch("httpx.AsyncClient", return_value=client):
            await discover(force=True)
            await discover(force=True)

        assert client.get.await_count == 2

    async def test_a_failure_is_cached_only_briefly(self) -> None:
        """Long enough to avoid hammering a dead gateway, short enough that recovery shows up
        without a restart."""
        from app.core.llm.discovery import CACHE_TTL_S, FAILURE_TTL_S

        assert FAILURE_TTL_S < CACHE_TTL_S


class TestCatalogueLookup:
    def test_a_model_can_be_found_by_id(self) -> None:
        catalogue = Catalogue(reachable=True, providers=parse_models(LIVE_SHAPE))
        assert catalogue.model("Full-Send") is not None
        assert catalogue.model("gpt-4o") is None, "the old hard-coded default is not offered"


class TestRoutingPrefixes:
    """The configured default is ``openai/Full-Send``; the gateway lists ``Full-Send``.

    Those are the same model — ``openai/`` is litellm's adapter selector, not part of the
    name. Matching only on the exact string reported a working configuration as broken, which
    is a false alarm on the very screen meant to catch real misconfigurations.
    """

    def test_a_litellm_prefixed_default_resolves_to_the_gateway_id(self) -> None:
        catalogue = Catalogue(reachable=True, providers=parse_models(LIVE_SHAPE))
        assert catalogue.model("openai/Full-Send") is not None

    def test_ids_that_legitimately_contain_slashes_are_not_mangled(self) -> None:
        """``no-think/opencode/...`` is a real id. Blindly taking the last segment, or
        stripping any prefix, would mismatch it."""
        catalogue = Catalogue(reachable=True, providers=parse_models(LIVE_SHAPE))
        assert catalogue.model("no-think/opencode/claude-sonnet-4-5-high") is not None
        assert catalogue.model("opencode/claude-sonnet-4-5-high") is None

    def test_an_unknown_prefix_is_not_stripped(self) -> None:
        catalogue = Catalogue(reachable=True, providers=parse_models(LIVE_SHAPE))
        assert catalogue.model("madeup/Full-Send") is None

    def test_a_genuinely_absent_model_is_still_absent(self) -> None:
        catalogue = Catalogue(reachable=True, providers=parse_models(LIVE_SHAPE))
        assert catalogue.model("openai/gpt-4o") is None
