"""Wire format for the AI control plane.

Two rules run through these shapes.

``reachable`` and ``recorded`` are separate from emptiness. A gateway that cannot be reached
and a gateway with no models are different problems; so are "no calls made in this period"
and "usage tracking is broken". Collapsing either pair into an empty list is what makes a
settings screen impossible to debug.

Absent metadata is ``None``, never a default. A model that does not report a context length
gets nothing, and the UI says so — a plausible-looking 8192 is the kind of number an operator
would plan around.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AIModelInfo(BaseModel):
    """One model the gateway says it can route to."""

    id: str
    provider: str
    #: Normalised names: tool_calling, vision, reasoning, temperature, effort_tiers. Empty
    #: means the gateway reported none, not that the model supports none.
    capabilities: list[str] = Field(default_factory=list)
    context_length: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    is_default: bool = False


class AIProviderInfo(BaseModel):
    """A provider, as the gateway itself groups models."""

    id: str
    model_count: int = 0
    models: list[AIModelInfo] = Field(default_factory=list)


class AICatalogue(BaseModel):
    """What the configured gateway offers — discovered, not declared."""

    reachable: bool
    #: Verbatim when unreachable. "Connection refused" and "401" need different fixes.
    error: str | None = None
    base_url: str = ""
    provider_count: int = 0
    model_count: int = 0
    default_model: str = ""
    #: False when the configured default names a model the gateway does not list — a real
    #: misconfiguration that otherwise only surfaces as a failed run much later.
    default_model_available: bool = False
    providers: list[AIProviderInfo] = Field(default_factory=list)


class AIUsageBreakdown(BaseModel):
    """Totals for one provider, model or purpose."""

    key: str
    total_tokens: int = 0
    cost_usd: float = 0.0
    requests: int = 0


class AIUsageReport(BaseModel):
    """Recorded LLM usage for the current user. Summed from rows, never estimated."""

    period: str
    #: False when no calls were recorded in the window — distinct from a row of zeroes,
    #: which would read as "measured, and it was nothing".
    recorded: bool = False
    requests: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    by_provider: list[AIUsageBreakdown] = Field(default_factory=list)
    by_model: list[AIUsageBreakdown] = Field(default_factory=list)
    by_purpose: list[AIUsageBreakdown] = Field(default_factory=list)
    top_model: str | None = None
    top_purpose: str | None = None
