"""Discover what the LLM gateway actually offers, instead of asserting it.

``/settings/llm-providers`` used to return a hard-coded list of five providers with
hard-coded model names — ``gpt-4o``, ``llama-3.1-70b-versatile``, ``gemini-pro`` — and
reported each as "configured" purely from whether an API key string was non-empty. None of
that was checked against anything. Against the gateway this deployment actually runs, the
real answer is 648 models across 16 providers, and not one of the five hard-coded names is
among them.

So this module asks. OmniRoute is OpenAI-compatible, which means ``GET /v1/models`` is the
standard discovery endpoint, and it returns considerably more than ids: the owning provider,
tool-calling / vision / reasoning capabilities, and context limits. That is enough to build a
capability-aware UI without maintaining a parallel list that would immediately drift.

Three things this deliberately does **not** do:

* **Invent metadata.** A model that does not report a context length has ``None``, not a
  guess. The UI prints "not reported by the gateway".
* **Fail loudly on an unreachable gateway.** Discovery returning nothing is a normal state —
  the gateway is a local process that may be off. The caller gets an explicit
  ``reachable=False`` with the error, so the UI can say "cannot reach the gateway" rather
  than "no models available", which are different problems with different fixes.
* **Hold the result forever.** A short TTL cache keeps a settings page from issuing a
  quarter-megabyte fetch on every render, while still reflecting a gateway restart within
  the minute.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from app.config.settings import get_settings

logger = structlog.get_logger(__name__)

#: How long a successful catalogue is reused. The gateway's model list changes when the
#: operator reconfigures it, which is rare; re-fetching 250KB per settings render is not.
CACHE_TTL_S = 60.0
#: A failed probe is retried sooner — an operator who has just started the gateway should not
#: wait a full minute to see it come alive.
FAILURE_TTL_S = 10.0
REQUEST_TIMEOUT_S = 8.0

#: litellm adapter prefixes. A configured model of ``openai/Full-Send`` means "route via the
#: OpenAI-compatible adapter to the model Full-Send" — the prefix is not part of the id the
#: gateway publishes, so it is stripped before matching against the catalogue.
_ROUTING_PREFIXES = frozenset({
    "openai", "azure", "anthropic", "bedrock", "vertex_ai", "gemini", "groq", "openrouter",
    "ollama", "deepseek", "mistral", "together_ai", "fireworks_ai", "github",
})

#: Capability flags the gateway reports. Normalised because the payload uses several spellings
#: for the same idea (``thinking`` / ``supportsThinking``), and a UI keyed off the raw strings
#: would show the same capability twice under different names.
_CAPABILITY_ALIASES = {
    "supportsthinking": "reasoning",
    "thinking": "reasoning",
    "reasoning": "reasoning",
    "tool_calling": "tool_calling",
    "tools": "tool_calling",
    "vision": "vision",
    "temperature": "temperature",
    "effort_tiers": "effort_tiers",
}


@dataclass(frozen=True)
class DiscoveredModel:
    """One model the gateway says it can route to."""

    id: str
    provider: str
    #: Normalised capability names, e.g. ``{"tool_calling", "vision"}``. Empty means the
    #: gateway reported none — not that the model has none.
    capabilities: frozenset[str] = field(default_factory=frozenset)
    context_length: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class DiscoveredProvider:
    """A provider, as the gateway groups its own models."""

    id: str
    models: tuple[DiscoveredModel, ...]

    @property
    def model_count(self) -> int:
        return len(self.models)


@dataclass(frozen=True)
class Catalogue:
    """What the gateway offers right now, or why that could not be established."""

    reachable: bool
    providers: tuple[DiscoveredProvider, ...] = ()
    #: Populated only when ``reachable`` is False. Shown to the operator verbatim, because
    #: "connection refused" and "401 unauthorized" need different fixes.
    error: str | None = None
    base_url: str = ""
    fetched_at: float = 0.0

    @property
    def model_count(self) -> int:
        return sum(p.model_count for p in self.providers)

    def model(self, model_id: str) -> DiscoveredModel | None:
        """Find a model by id, tolerating a litellm routing prefix.

        The configured default is ``openai/Full-Send`` while the gateway lists ``Full-Send``.
        Those are the same model: ``openai/`` is litellm's instruction to use the
        OpenAI-compatible adapter, not part of the model's name. Matching only on the exact
        string reported this working configuration as broken.

        The prefix is stripped only when it names a known adapter, because plenty of real ids
        contain slashes of their own (``no-think/opencode/claude-sonnet-4-5-high``) and
        blindly taking the last segment would mismatch those.
        """
        wanted = {model_id}
        head, _, tail = model_id.partition("/")
        if tail and head.casefold() in _ROUTING_PREFIXES:
            wanted.add(tail)

        for provider in self.providers:
            for model in provider.models:
                if model.id in wanted:
                    return model
        return None


def _normalise_capabilities(raw: Any) -> frozenset[str]:
    """Map the gateway's capability dict onto stable names, dropping anything falsey."""
    if not isinstance(raw, dict):
        return frozenset()
    found: set[str] = set()
    for key, value in raw.items():
        if not value:
            continue
        canonical = _CAPABILITY_ALIASES.get(str(key).casefold())
        if canonical:
            found.add(canonical)
    return frozenset(found)


def _as_int(value: Any) -> int | None:
    """A positive int, or ``None``. Never a fabricated default."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_models(payload: Any) -> tuple[DiscoveredProvider, ...]:
    """Turn an OpenAI-compatible ``/v1/models`` body into providers and models.

    Tolerant by design: a gateway that omits ``owned_by``, or returns a bare list instead of
    ``{"data": [...]}``, still yields a usable catalogue. The alternative — refusing to parse
    a slightly different shape — would present a working gateway as unreachable.
    """
    rows: list[Any]
    if isinstance(payload, dict):
        raw = payload.get("data")
        rows = raw if isinstance(raw, list) else []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    by_provider: dict[str, list[DiscoveredModel]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        provider = str(row.get("owned_by") or "").strip() or "unknown"
        by_provider.setdefault(provider, []).append(
            DiscoveredModel(
                id=model_id,
                provider=provider,
                capabilities=_normalise_capabilities(row.get("capabilities")),
                context_length=_as_int(row.get("context_length")),
                max_input_tokens=_as_int(row.get("max_input_tokens")),
                max_output_tokens=_as_int(row.get("max_output_tokens")),
            )
        )

    return tuple(
        DiscoveredProvider(id=name, models=tuple(sorted(models, key=lambda m: m.id)))
        for name, models in sorted(by_provider.items())
    )


_cache: Catalogue | None = None


def _cache_is_fresh(cached: Catalogue) -> bool:
    ttl = CACHE_TTL_S if cached.reachable else FAILURE_TTL_S
    return (time.monotonic() - cached.fetched_at) < ttl


async def discover(*, force: bool = False) -> Catalogue:
    """Ask the gateway what it can route to.

    ``force`` bypasses the cache, which is what the settings screen's "Refresh models" action
    uses — an operator who has just reconfigured the gateway should not be told to wait.
    """
    global _cache
    if not force and _cache is not None and _cache_is_fresh(_cache):
        return _cache

    llm = get_settings().llm
    base = (llm.api_base or "").rstrip("/")
    if not base:
        # Not an error: a deployment with no gateway configured is a valid state, and saying
        # "not configured" is more useful than a connection error nobody can act on.
        _cache = Catalogue(
            reachable=False,
            error="No LLM gateway is configured (LLM__API_BASE is empty).",
            fetched_at=time.monotonic(),
        )
        return _cache

    url = f"{base}/models"
    # Match the actual completion client's auth field (see core.llm.client), not
    # ``openai_api_key`` — that field is unrelated to gateway auth, so this previously sent
    # no Authorization header at all and reported a configured, working gateway as down.
    key = llm.api_base_key.get_secret_value() or "local-gateway"
    headers: dict[str, str] = {"Authorization": f"Bearer {key}"}

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            providers = parse_models(response.json())
    except Exception as exc:
        # Deliberately broad: a gateway that is off, slow, unauthorised or returning HTML all
        # end here, and every one of them means the same thing to the caller — the catalogue
        # could not be established. The message distinguishes them for the operator.
        logger.warning("llm_discovery.failed", url=url, error=str(exc))
        _cache = Catalogue(
            reachable=False,
            error=f"{type(exc).__name__}: {exc}"[:300],
            base_url=base,
            fetched_at=time.monotonic(),
        )
        return _cache

    _cache = Catalogue(
        reachable=True, providers=providers, base_url=base, fetched_at=time.monotonic()
    )
    logger.info(
        "llm_discovery.ok",
        providers=len(providers),
        models=_cache.model_count,
        base_url=base,
    )
    return _cache


def reset_cache() -> None:
    """Drop the cached catalogue. Used by tests and by an explicit refresh."""
    global _cache
    _cache = None
