"""browser-use runtime factory (browser-use 0.11.5).

Builds a per-tenant ``BrowserProfile`` (session hydration + identity + domain scoping)
and an apply ``Agent`` with reliability config and typed output.

NOTE: constructing a ``BrowserProfile`` is pure config (no browser launched). Actually
*running* the agent requires a real (headful / Xvfb) browser environment, a valid
platform ``storage_state`` (from an assisted login), and a configured LLM key — that
end-to-end path is exercised in a real-browser spike, not in CI.
"""

from __future__ import annotations

from typing import Any

from app.config.settings import get_settings
from app.core.automation.runtime.result import ApplicationResult


def build_browser_profile(
    *,
    storage_state: dict[str, Any] | None = None,
    proxy: Any | None = None,
    user_agent: str | None = None,
    allowed_domains: list[str] | None = None,
    headless: bool | None = None,
) -> Any:
    """Construct a per-tenant ``BrowserProfile`` (hydrated session + stable identity)."""
    from browser_use import BrowserProfile

    settings = get_settings().browser
    return BrowserProfile(
        storage_state=storage_state,
        proxy=proxy,
        user_agent=user_agent,
        allowed_domains=allowed_domains,
        headless=settings.headless if headless is None else headless,
        keep_alive=False,
    )


def build_apply_llm(api_key: str | None, model: str = "anthropic/claude-sonnet-5-5") -> Any:
    """Build the browser-use LLM the agent reasons with, routed the way the app's own LLM
    client routes the same model id.

    * ``bedrock/<model-id>``: AWS Bedrock via the standard AWS credential chain, no api_key.
    * ``anthropic/<model>`` or ``claude-...``: the Anthropic API directly, with the per-user
      key if one is stored, else ``ANTHROPIC_API_KEY``. This used to fall through to
      ``ChatOpenAI``, which sent a Claude model id to OpenAI, so no live apply could run on the
      production LLM at all.
    * anything else with ``LLM__API_BASE`` set: the OpenAI-compatible gateway, with its own
      credential.
    * anything else: OpenAI with the per-user key.
    """
    import os

    from app.core.llm.client import is_anthropic_model

    if is_anthropic_model(model):
        from browser_use.llm.anthropic.chat import ChatAnthropic

        return ChatAnthropic(
            model=model.split("/", 1)[1] if model.startswith("anthropic/") else model,
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY") or None,
        )
    if model.startswith("bedrock/"):
        from browser_use.llm import ChatAnthropicBedrock

        return ChatAnthropicBedrock(
            model=model.split("/", 1)[1],
            aws_region=get_settings().llm.bedrock_region,
        )
    from browser_use import ChatOpenAI

    from app.core.llm.requirements import gateway_credential, is_gateway_routed

    if is_gateway_routed(model):
        return ChatOpenAI(
            model=model.split("/", 1)[1] if model.startswith("openai/") else model,
            api_key=gateway_credential(),
            base_url=get_settings().llm.api_base,
        )
    return ChatOpenAI(model=model, api_key=api_key)


def build_apply_agent(
    task: str,
    *,
    llm: Any,
    profile: Any,
    tools: Any | None = None,
    extend_system_message: str = "",
    should_stop: Any | None = None,
) -> Any:
    """Build the apply ``Agent`` with the typed ``ApplicationResult`` output schema.

    ``should_stop`` (an async, zero-arg callable returning bool) is browser-use's own
    documented mechanism for actually halting a multi-step run — checked at every step
    boundary — as opposed to a single action merely failing and leaving the LLM free to try
    something else. Used by the pre-submit confirmation gate (``runtime.confirmation``) to
    turn an operator's rejection into the run actually ending.
    """
    from browser_use import Agent, BrowserSession

    settings = get_settings().browser
    session = BrowserSession(browser_profile=profile)
    return Agent(
        task=task,
        llm=llm,
        browser_session=session,
        tools=tools,
        output_model_schema=ApplicationResult,
        max_failures=settings.max_failures,
        extend_system_message=extend_system_message,
        register_should_stop_callback=should_stop,
    )
