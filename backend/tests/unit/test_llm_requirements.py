"""When a per-user API key is genuinely required.

This rule blocked every application on a working system. The operator's models are all routed
through a local gateway, which authenticates with its own credential — but the apply path
demanded a personal ``openai`` key anyway and refused to run without one. The check disagreed
with what ``llm/client.py`` actually did, and the operator was told to configure a key they
did not need and could not usefully supply.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from app.core.llm import requirements
from app.core.llm.requirements import (
    is_gateway_routed,
    is_platform_authenticated,
    llm_key_required,
)


@pytest.fixture
def gateway(monkeypatch):
    """Point the settings at a gateway, or at nothing, per test."""
    def configure(api_base: str = "", api_base_key: str = ""):
        from app.config.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings.llm, "api_base", api_base, raising=False)
        monkeypatch.setattr(settings.llm, "api_base_key", api_base_key, raising=False)
    return configure


class TestGatewayRouting:
    def test_a_configured_gateway_serves_ordinary_models(self, gateway) -> None:
        gateway(api_base="http://localhost:20128/v1")
        assert is_gateway_routed("openai/Full-Send")
        assert is_gateway_routed("anthropic/claude-sonnet-4")

    def test_bedrock_bypasses_the_gateway(self, gateway) -> None:
        """The client sends everything except Bedrock through ``api_base``."""
        gateway(api_base="http://localhost:20128/v1")
        assert not is_gateway_routed("bedrock/claude")

    def test_no_gateway_means_direct_calls(self, gateway) -> None:
        gateway(api_base="")
        assert not is_gateway_routed("openai/gpt-4")


class TestWhenAKeyIsRequired:
    def test_a_gateway_routed_model_needs_no_personal_key(self, gateway) -> None:
        """The exact case that blocked every application on a working system."""
        gateway(api_base="http://localhost:20128/v1", api_base_key="sk-local-xyz")
        assert not llm_key_required("openai", "openai/Full-Send")

    def test_bedrock_needs_no_personal_key(self, gateway) -> None:
        gateway(api_base="")
        assert not llm_key_required("bedrock", "bedrock/claude-sonnet")
        assert not llm_key_required("openai", "bedrock/claude-sonnet")

    def test_a_direct_provider_call_still_needs_one(self, gateway) -> None:
        """The rule must not become "never ask for a key" — that would swap one silent
        failure for another, at the point of the actual API call."""
        gateway(api_base="")
        assert llm_key_required("openai", "gpt-4o")
        assert llm_key_required("anthropic", "claude-sonnet-4")

    def test_platform_authentication_is_the_union_of_both(self, gateway) -> None:
        gateway(api_base="http://localhost:20128/v1")
        assert is_platform_authenticated("openai", "openai/Full-Send")
        assert is_platform_authenticated("bedrock", "bedrock/x")
        gateway(api_base="")
        assert not is_platform_authenticated("openai", "gpt-4o")


class TestTheRuleHasExactlyOneDefinition:
    """It had three, and they had already drifted apart."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "app/services/readiness.py",
            "app/core/automation/runtime/apply.py",
        ],
    )
    def test_no_caller_re_derives_the_bedrock_check(self, module_path: str) -> None:
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        source = (root / module_path).read_text(encoding="utf-8")
        # A local `is_bedrock = provider == "bedrock" or ...` is the shape that drifted.
        assert 'provider == "bedrock" or' not in source, (
            f"{module_path} re-derives the rule instead of calling llm_key_required"
        )
        assert "llm_key_required" in source

    def test_the_gateway_credential_matches_the_client_fallback(self) -> None:
        """``client.py`` falls back to "local-gateway" when no key is set; a different default
        here would mean the readiness check and the actual call authenticate differently."""
        source = inspect.getsource(requirements.gateway_credential)
        assert "local-gateway" in source

    def test_the_module_reads_settings_rather_than_hard_coding_a_host(self) -> None:
        tree = ast.parse(inspect.getsource(requirements))
        literals = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert not any("localhost" in v or "http://" in v for v in literals), (
            "the gateway address belongs in settings, not in this rule"
        )
