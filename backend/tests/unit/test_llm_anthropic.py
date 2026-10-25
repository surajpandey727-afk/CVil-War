"""The Anthropic route through the litellm gateway.

Pins the request shape the Claude 5.5 models require (no temperature, no json_object mode,
key from ANTHROPIC_API_KEY only, never sent through the OmniRoute api_base), the purpose-based
model choice (Haiku for cheap classification), and the explicit fallback chain.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, SecretStr

from app.config.settings import LLMSettings
from app.core.exceptions import LLMProviderError
from app.core.llm.client import LLMClient, anthropic_key_configured, is_anthropic_model

SONNET = "anthropic/claude-sonnet-5-5"
HAIKU = "anthropic/claude-haiku-5-5"


def _settings(**llm_overrides: object) -> MagicMock:
    llm = LLMSettings(
        api_base="http://localhost:20128/v1",
        api_base_key=SecretStr("gateway-key"),
        **llm_overrides,
    )
    settings = MagicMock()
    settings.llm = llm
    return settings


def _response(content: str = '{"ok": true}', finish: str = "stop") -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = finish
    resp.usage = MagicMock(prompt_tokens=5, completion_tokens=7, total_tokens=12)
    return resp


def _client(settings: MagicMock) -> LLMClient:
    with patch("app.core.llm.client.get_settings", return_value=settings):
        return LLMClient()


@pytest.fixture(autouse=True)
def _hermetic_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's local LLM__* overrides (e.g. an OmniRoute default model) must not leak in."""
    import os

    for name in list(os.environ):
        if name.upper().startswith("LLM__"):
            monkeypatch.delenv(name)


@pytest.fixture()
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    return "sk-ant-test-not-real"


class TestDefaults:
    def test_default_route_is_claude_sonnet_with_haiku_for_classification(self) -> None:
        llm = LLMSettings()
        assert llm.default_model == SONNET
        assert llm.classify_model == HAIKU
        assert llm.preferred_provider == "anthropic"
        assert llm.fallback_models == [HAIKU]

    def test_model_detection(self) -> None:
        assert is_anthropic_model(SONNET)
        assert is_anthropic_model("claude-haiku-5-5")
        assert not is_anthropic_model("openai/Full-Send")
        assert not is_anthropic_model("bedrock/anthropic.claude-sonnet-4-5")

    def test_key_presence_is_reported_without_the_value(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert anthropic_key_configured() is False
        monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
        assert anthropic_key_configured() is False
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        assert anthropic_key_configured() is True


class TestModelChain:
    def test_general_purpose_uses_sonnet_then_haiku(self) -> None:
        assert _client(_settings())._get_model_chain(None) == [SONNET, HAIKU]

    def test_classification_purpose_uses_haiku_without_duplicating_it(self) -> None:
        chain = _client(_settings())._get_model_chain(None, "harness_judge")
        assert chain == [HAIKU]

    def test_explicit_fallbacks_replace_synthesised_provider_fallbacks(self) -> None:
        # The legacy rule would have produced groq/claude-sonnet-5-5 — a model that exists nowhere.
        chain = _client(_settings(fallback_models=[HAIKU, "openai/Full-Send"]))._get_model_chain(
            None
        )
        assert chain == [SONNET, HAIKU, "openai/Full-Send"]
        assert not any(m.startswith("groq/") for m in chain)

    def test_an_explicit_model_wins_over_the_purpose_default(self) -> None:
        chain = _client(_settings())._get_model_chain("anthropic/claude-opus-5-5", "harness_judge")
        assert chain[0] == "anthropic/claude-opus-5-5"


class TestRequestShape:
    async def test_anthropic_call_omits_temperature_and_json_mode_and_skips_the_gateway(
        self, key: str
    ) -> None:
        client = _client(_settings(fallback_models=[]))
        with patch("app.core.llm.client.litellm") as litellm:
            litellm.acompletion = AsyncMock(return_value=_response())
            litellm.completion_cost.return_value = 0.0
            await client.complete("hi", response_format={"type": "json_object"}, temperature=0.2)
        kwargs = litellm.acompletion.call_args.kwargs
        assert kwargs["model"] == SONNET
        assert kwargs["api_key"] == key
        assert "temperature" not in kwargs
        assert "response_format" not in kwargs
        assert "api_base" not in kwargs  # never routed through OmniRoute
        assert kwargs["max_tokens"] >= 8192

    async def test_non_anthropic_models_keep_the_gateway_and_temperature(self, key: str) -> None:
        client = _client(_settings(default_model="openai/Full-Send", fallback_models=[]))
        with patch("app.core.llm.client.litellm") as litellm:
            litellm.acompletion = AsyncMock(return_value=_response())
            litellm.completion_cost.return_value = 0.0
            await client.complete("hi", temperature=0.2)
        kwargs = litellm.acompletion.call_args.kwargs
        assert kwargs["api_base"] == "http://localhost:20128/v1"
        assert kwargs["temperature"] == 0.2

    async def test_missing_key_skips_anthropic_and_uses_the_fallback(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = _client(_settings(fallback_models=["openai/Full-Send"]))
        with patch("app.core.llm.client.litellm") as litellm:
            litellm.acompletion = AsyncMock(return_value=_response("from gateway"))
            litellm.completion_cost.return_value = 0.0
            result = await client.complete("hi")
        assert result.model == "openai/Full-Send"
        assert litellm.acompletion.await_count == 1  # no keyless call to Anthropic was made

    async def test_missing_key_and_no_fallback_is_a_clear_error(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = _client(_settings(fallback_models=[]))
        with (
            patch("app.core.llm.client.litellm.acompletion", new=AsyncMock()) as call,
            pytest.raises(LLMProviderError) as e,
        ):
            await client.complete("hi")
        call.assert_not_awaited()
        assert "ANTHROPIC_API_KEY is not set" in str(e.value)
        assert "sk-" not in str(e.value)

    async def test_a_refusal_falls_through_to_the_next_model(self, key: str) -> None:
        client = _client(_settings())
        with patch("app.core.llm.client.litellm") as litellm:
            litellm.acompletion = AsyncMock(
                side_effect=[_response("", finish="refusal"), _response('{"ok": 1}')]
            )
            litellm.completion_cost.return_value = 0.0
            result = await client.complete("hi")
        assert result.model == HAIKU
        assert result.content == '{"ok": 1}'


class _Verdict(BaseModel):
    verdict: str
    confidence: float


class TestStructuredOutputValidation:
    async def test_invalid_json_from_claude_is_rejected_not_passed_on(self, key: str) -> None:
        client = _client(_settings(fallback_models=[]))
        with patch("app.core.llm.client.litellm") as litellm:
            litellm.acompletion = AsyncMock(return_value=_response('{"verdict": "yes"}'))
            litellm.completion_cost.return_value = 0.0
            with pytest.raises(LLMProviderError, match="Failed to parse structured output"):
                await client.complete_with_structured_output("judge", _Verdict)

    async def test_valid_json_inside_prose_is_salvaged_and_validated(self, key: str) -> None:
        client = _client(_settings(fallback_models=[]))
        body = 'Here you go:\n```json\n{"verdict": "success", "confidence": 0.9}\n```'
        with patch("app.core.llm.client.litellm") as litellm:
            litellm.acompletion = AsyncMock(return_value=_response(body))
            litellm.completion_cost.return_value = 0.0
            out = await client.complete_with_structured_output("judge", _Verdict)
        assert out == _Verdict(verdict="success", confidence=0.9)
