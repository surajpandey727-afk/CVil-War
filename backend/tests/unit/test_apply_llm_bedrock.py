"""build_apply_llm routes bedrock/<id> models through AWS Bedrock (no api_key)."""

from __future__ import annotations

from app.core.automation.runtime.factory import build_apply_llm


def test_bedrock_model_returns_bedrock_chat_without_api_key() -> None:
    llm = build_apply_llm(None, "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert type(llm).__name__ == "ChatAnthropicBedrock"
    # The bedrock model id is stripped of the ``bedrock/`` routing prefix.
    assert getattr(llm, "model", "").startswith("anthropic.claude")


def test_non_bedrock_model_uses_openai_byo_key() -> None:
    llm = build_apply_llm("sk-test", "gpt-4o")
    assert type(llm).__name__ == "ChatOpenAI"


def test_a_claude_model_goes_to_anthropic_not_openai(monkeypatch) -> None:
    """The production model is anthropic/claude-sonnet-5-5. It used to fall through to
    ChatOpenAI, so every live apply sent a Claude model id to OpenAI and failed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    llm = build_apply_llm(None, "anthropic/claude-sonnet-5-5")
    assert type(llm).__name__ == "ChatAnthropic"
    assert llm.model == "claude-sonnet-5-5"
    assert llm.api_key == "sk-ant-test-not-real"


def test_a_stored_per_user_key_wins_over_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    llm = build_apply_llm("sk-ant-user", "claude-haiku-5-5")
    assert llm.api_key == "sk-ant-user"
    assert llm.model == "claude-haiku-5-5"


def test_a_gateway_model_uses_the_gateway(monkeypatch) -> None:
    from app.config.settings import get_settings

    monkeypatch.setattr(get_settings().llm, "api_base", "http://127.0.0.1:20128/v1")
    llm = build_apply_llm(None, "openai/auto/claude-sonnet")
    assert type(llm).__name__ == "ChatOpenAI"
    assert str(llm.base_url).startswith("http://127.0.0.1:20128")
    assert llm.model == "auto/claude-sonnet"


def test_claude_needs_no_per_user_key_when_the_deployment_has_one(monkeypatch) -> None:
    from app.config.settings import get_settings
    from app.core.llm.requirements import is_gateway_routed, llm_key_required

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setattr(get_settings().llm, "api_base", "http://gw/v1")
    assert not is_gateway_routed("anthropic/claude-sonnet-5-5")  # sent direct, not via gateway
    assert not llm_key_required("anthropic", "anthropic/claude-sonnet-5-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert llm_key_required("anthropic", "anthropic/claude-sonnet-5-5")
