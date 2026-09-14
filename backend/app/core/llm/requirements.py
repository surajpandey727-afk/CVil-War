"""Whether a model needs a per-user API key at all.

One question asked in three places — the apply worker, the pre-apply readiness check, and
anything else that gates on credentials — so it lives here rather than being re-derived. The
two copies that existed had already drifted from what the client actually does, which is the
specific failure this prevents: the operator was told "No API key is configured for openai"
and blocked from applying, while ``llm/client.py`` was quite happily routing every call
through the local gateway using the gateway's own key.
"""

from __future__ import annotations

from app.config.settings import get_settings


def _secret(value: object) -> str:
    """Read a value that may be a pydantic ``SecretStr`` or a plain string."""
    getter = getattr(value, "get_secret_value", None)
    return (getter() if callable(getter) else value) or ""  # type: ignore[return-value]


def is_gateway_routed(model: str) -> bool:
    """True when this model is served through the configured gateway rather than direct.

    Mirrors the condition in :mod:`app.core.llm.client`, which sends everything except
    Bedrock through ``api_base`` when one is set. A gateway presents its own credential
    upstream, so the user never holds a provider key for these calls.
    """
    llm = get_settings().llm
    return bool(llm.api_base) and not model.startswith("bedrock/")


def is_platform_authenticated(provider: str, model: str) -> bool:
    """True when the call authenticates without a per-user key.

    Two ways that happens: Bedrock uses the AWS credential chain, and a configured gateway
    uses its own key. Either way, demanding a key from the operator blocks work that would
    otherwise succeed.
    """
    return provider == "bedrock" or model.startswith("bedrock/") or is_gateway_routed(model)


def llm_key_required(provider: str, model: str) -> bool:
    """Whether the operator must supply an API key for ``provider`` before the agent can run."""
    return not is_platform_authenticated(provider, model)


def gateway_credential() -> str:
    """The credential the gateway itself is called with, matching the client's fallback."""
    return _secret(get_settings().llm.api_base_key) or "local-gateway"
