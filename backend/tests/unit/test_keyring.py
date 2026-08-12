"""Tests for the rotating LLM key pool.

The point of the pool is that a *spent* key rotates to the next key on the SAME model,
instead of degrading to a weaker fallback provider. These tests pin that behaviour plus the
two cooldown policies, and assert raw keys never leak into masked output.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import litellm
import pytest

from app.core.llm.client import LLMClient, ResolvedLLMCredentials
from app.core.llm.keyring import (
    EXHAUSTED_COOLDOWN_S,
    RATE_LIMIT_COOLDOWN_S,
    KeyRing,
    is_quota_exhausted,
    mask_key,
    reset_keyrings,
)

K1 = "sk-11111111111111111111111111111111"
K2 = "sk-22222222222222222222222222222222"
K3 = "sk-33333333333333333333333333333333"


class TestParsing:
    def test_from_csv_strips_blanks_and_duplicates(self) -> None:
        ring = KeyRing.from_csv("deepseek", f" {K1} , {K2},, {K1} ,")
        assert ring.all_keys() == [K1, K2]

    def test_empty_config_is_not_configured(self) -> None:
        assert KeyRing.from_csv("deepseek", "   ,  ,").configured is False


class TestRotation:
    def test_healthy_pool_keeps_reusing_the_first_key(self) -> None:
        """No round-robin: a working key should stay hot rather than cycling needlessly."""
        ring = KeyRing.from_csv("deepseek", f"{K1},{K2},{K3}")
        assert ring.next_key(_now=0) == K1
        ring.mark_success(K1)
        assert ring.next_key(_now=0) == K1

    def test_exhausted_key_is_skipped_and_the_next_takes_over(self) -> None:
        ring = KeyRing.from_csv("deepseek", f"{K1},{K2},{K3}")
        ring.mark_exhausted(K1, _now=0)
        assert ring.next_key(_now=0) == K2
        ring.mark_exhausted(K2, _now=0)
        assert ring.next_key(_now=0) == K3

    def test_all_keys_spent_yields_none(self) -> None:
        ring = KeyRing.from_csv("deepseek", f"{K1},{K2}")
        ring.mark_exhausted(K1, _now=0)
        ring.mark_exhausted(K2, _now=0)
        assert ring.next_key(_now=0) is None
        assert ring.usable_keys(_now=0) == []

    def test_exhausted_key_returns_after_its_cooldown(self) -> None:
        """Credit can be topped up, so the park must expire rather than be permanent."""
        ring = KeyRing.from_csv("deepseek", K1)
        ring.mark_exhausted(K1, _now=0)
        assert ring.next_key(_now=EXHAUSTED_COOLDOWN_S - 1) is None
        assert ring.next_key(_now=EXHAUSTED_COOLDOWN_S + 1) == K1

    def test_rate_limit_cooldown_is_far_shorter_than_exhaustion(self) -> None:
        """429 is transient; 402 is not. Conflating them would either hammer a spent key or
        park a merely-throttled one for hours."""
        ring = KeyRing.from_csv("deepseek", f"{K1},{K2}")
        ring.mark_rate_limited(K1, _now=0)
        assert ring.next_key(_now=0) == K2
        assert ring.next_key(_now=RATE_LIMIT_COOLDOWN_S + 1) == K1
        assert RATE_LIMIT_COOLDOWN_S < EXHAUSTED_COOLDOWN_S

    def test_success_clears_a_cooldown(self) -> None:
        ring = KeyRing.from_csv("deepseek", K1)
        ring.mark_rate_limited(K1, _now=0)
        assert ring.next_key(_now=0) is None
        ring.mark_success(K1)
        assert ring.next_key(_now=0) == K1

    def test_marking_an_unknown_key_is_a_no_op(self) -> None:
        ring = KeyRing.from_csv("deepseek", K1)
        ring.mark_exhausted("sk-not-in-the-pool", _now=0)
        assert ring.next_key(_now=0) == K1


class TestMasking:
    def test_masked_key_never_contains_the_secret_body(self) -> None:
        masked = mask_key(K1)
        assert K1 not in masked
        assert masked.startswith("sk-1111")
        assert masked.endswith("1111")

    def test_short_values_reveal_nothing(self) -> None:
        assert mask_key("sk-abc") == "…"

    def test_status_snapshot_is_masked_and_json_safe(self) -> None:
        ring = KeyRing.from_csv("deepseek", f"{K1},{K2}")
        ring.mark_exhausted(K1, _now=0)
        rows = ring.status(_now=0)
        blob = str(rows)
        assert K1 not in blob and K2 not in blob
        assert rows[0]["status"] == "exhausted"
        assert rows[0]["cooldown_remaining_s"] > 0
        assert rows[1]["status"] == "available"


class TestExhaustionDetection:
    @pytest.mark.parametrize(
        "message",
        [
            "Error code: 402 - Insufficient Balance",
            "You exceeded your current quota, please check your plan",
            "insufficient_quota",
            "Your credit balance is too low to access the API",
            "402 Payment Required",
        ],
    )
    def test_spent_key_messages_are_detected(self, message: str) -> None:
        assert is_quota_exhausted(Exception(message)) is True

    @pytest.mark.parametrize(
        "message",
        [
            "Rate limit reached for requests",
            "Connection error",
            "context_length_exceeded: too many tokens",
            "model not found",
        ],
    )
    def test_transient_and_request_errors_are_not_exhaustion(self, message: str) -> None:
        """Misclassifying these would park a perfectly good key for hours."""
        assert is_quota_exhausted(Exception(message)) is False

    def test_http_402_status_is_detected_without_a_matching_message(self) -> None:
        exc = Exception("something opaque")
        exc.status_code = 402  # type: ignore[attr-defined]
        assert is_quota_exhausted(exc) is True


# ---------------------------------------------------------------------------
# Client integration — the behaviour that actually matters
# ---------------------------------------------------------------------------


def _settings_with_pool(raw_keys: str) -> MagicMock:
    settings = MagicMock()
    llm = MagicMock()
    llm.default_model = "deepseek/deepseek-chat"
    llm.temperature = 0.7
    llm.max_tokens = 1024
    llm.fallback_providers = []
    llm.bedrock_region = "us-east-1"
    for attr in (
        "portkey_api_key", "openai_api_key", "groq_api_key",
        "gemini_api_key", "openrouter_api_key",
    ):
        getattr(llm, attr).get_secret_value.return_value = ""
    llm.deepseek_api_keys.get_secret_value.return_value = raw_keys
    settings.llm = llm
    return settings


def _ok_response() -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "ok"
    usage = MagicMock()
    usage.prompt_tokens, usage.completion_tokens, usage.total_tokens = 1, 1, 2
    response.usage = usage
    return response


class TestClientRotatesKeys:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_keyrings()
        yield
        reset_keyrings()

    async def test_spent_key_rotates_to_the_next_key_on_the_same_model(self) -> None:
        """The whole point: a 402 must retry the SAME model with the next key, not fall back
        to a weaker provider or surface an error to the caller."""
        used: list[str] = []

        async def fake_acompletion(**kwargs):
            used.append(kwargs["api_key"])
            if kwargs["api_key"] == K1:
                raise litellm.APIError(
                    status_code=402, message="Insufficient Balance",
                    llm_provider="deepseek", model="deepseek-chat",
                )
            return _ok_response()

        with patch("app.core.llm.client.get_settings", return_value=_settings_with_pool(f"{K1},{K2}")), \
             patch("app.core.llm.client.litellm.acompletion", side_effect=fake_acompletion), \
             patch("app.core.llm.client.litellm.completion_cost", return_value=0.0):
            client = LLMClient()
            result = await client.complete("hi")

        assert result.content == "ok"
        assert used == [K1, K2], "should have tried the spent key, then rotated"
        assert result.model == "deepseek/deepseek-chat", "must stay on the same model"

    async def test_a_spent_key_is_not_retried_on_the_next_call(self) -> None:
        """Without the cooldown the pool would burn a doomed round-trip on every request."""
        used: list[str] = []

        async def fake_acompletion(**kwargs):
            used.append(kwargs["api_key"])
            if kwargs["api_key"] == K1:
                raise litellm.APIError(
                    status_code=402, message="Insufficient Balance",
                    llm_provider="deepseek", model="deepseek-chat",
                )
            return _ok_response()

        with patch("app.core.llm.client.get_settings", return_value=_settings_with_pool(f"{K1},{K2}")), \
             patch("app.core.llm.client.litellm.acompletion", side_effect=fake_acompletion), \
             patch("app.core.llm.client.litellm.completion_cost", return_value=0.0):
            await LLMClient().complete("first")
            used.clear()
            await LLMClient().complete("second")

        assert used == [K2], "the spent key must be skipped entirely on the next call"

    async def test_pool_is_shared_across_client_instances(self) -> None:
        """LLMClient is constructed per call site, so a per-instance ring would forget."""
        with patch("app.core.llm.client.get_settings", return_value=_settings_with_pool(f"{K1},{K2}")):
            a, b = LLMClient(), LLMClient()
        assert a._keyring is b._keyring

    async def test_byo_key_users_bypass_the_shared_pool(self) -> None:
        """A user supplying their own key must never be billed to the owner's pool."""
        used: list[str] = []

        async def fake_acompletion(**kwargs):
            used.append(kwargs["api_key"])
            return _ok_response()

        creds = ResolvedLLMCredentials(
            provider="deepseek",
            api_key="sk-user-own-key",
            default_model="deepseek/deepseek-chat",
        )
        with patch("app.core.llm.client.get_settings", return_value=_settings_with_pool(f"{K1},{K2}")), \
             patch("app.core.llm.client.litellm.acompletion", side_effect=fake_acompletion), \
             patch("app.core.llm.client.litellm.completion_cost", return_value=0.0):
            await LLMClient(credentials=creds).complete("hi")

        assert used == ["sk-user-own-key"]
