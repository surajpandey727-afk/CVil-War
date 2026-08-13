"""Job-source catalogue and health API.

Read-only. The UI needs to render a source rail that tells the truth about what can return
results before the operator commits a search to it, and the only place that answer exists is
``core.job_discovery.source_registry``.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.job_discovery.source_registry import (
    ALL_SOURCES,
    TIER_LABELS,
    SourceHealth,
    SourceTier,
    health_for,
)

router = APIRouter()


class SourceResponse(BaseModel):
    """One catalogue entry with its current health."""

    key: str
    label: str
    domain: str
    tier: str
    implemented: bool
    health: SourceHealth
    note: str = ""


class SourceTierResponse(BaseModel):
    """A tier and the sources inside it."""

    id: str
    name: str
    note: str
    sources: list[SourceResponse] = Field(default_factory=list)


class SourceCatalogueResponse(BaseModel):
    """The whole catalogue, grouped, plus the keys worth searching right now."""

    tiers: list[SourceTierResponse]
    live_keys: list[str]
    total: int


@router.get("/", response_model=SourceCatalogueResponse, summary="List job sources and health")
async def list_sources() -> SourceCatalogueResponse:
    """Return every known job source grouped by tier, with derived health."""
    tiers: list[SourceTierResponse] = []
    live_keys: list[str] = []

    for tier in SourceTier:
        name, note = TIER_LABELS[tier]
        entries: list[SourceResponse] = []
        for spec in ALL_SOURCES:
            if spec.tier is not tier:
                continue
            health = health_for(spec)
            if health is SourceHealth.LIVE:
                live_keys.append(spec.key)
            entries.append(
                SourceResponse(
                    key=spec.key,
                    label=spec.label,
                    domain=spec.domain,
                    tier=tier.value,
                    implemented=spec.implemented,
                    health=health,
                    note=spec.known_broken or spec.note,
                )
            )
        tiers.append(SourceTierResponse(id=tier.value, name=name, note=note, sources=entries))

    return SourceCatalogueResponse(tiers=tiers, live_keys=live_keys, total=len(ALL_SOURCES))
