"""Keyless API job sources, auto-registered with the shared platform registry.

Importing this package registers every adapter, so ``services.job_search`` picks them up
through the same ``platform_registry`` it already uses for the browser platforms — no change
to the search service.

Two families live here:

* **Aggregator boards** (``boards.py``) — Remotive, Jobicy, Arbeitnow, RemoteOK. Broad, remote-
  weighted coverage from one call each.
* **Employer ATS boards** (``ats.py``) — Greenhouse, Lever, Ashby, SmartRecruiters, one source
  per employer under ``careers:<slug>``. Narrow but authoritative: the vacancies straight from
  the company, usually before they reach any aggregator.

Every adapter here is :attr:`CostType.FREE`; nothing in this package can bill.
"""

from app.core.automation.platforms.registry import platform_registry
from app.core.job_discovery.sources.ats import (
    COMPANY_BOARDS,
    AshbySource,
    AtsBoardSource,
    GreenhouseSource,
    LeverSource,
    SmartRecruitersSource,
    build_career_sources,
)
from app.core.job_discovery.sources.base import ApiJobSource, CostType, SourceUnavailableError
from app.core.job_discovery.sources.boards import (
    ALL_SOURCES,
    ArbeitnowSource,
    JobicySource,
    RemoteOkSource,
    RemotiveSource,
)
from app.core.job_discovery.sources.uk_boards import UK_SOURCES, AdzunaSource, ReedSource

for _source in (*ALL_SOURCES, *UK_SOURCES):
    platform_registry.register(_source.source_name, _source)

#: ``careers:<slug> -> adapter class``, built once at import.
CAREER_SOURCES = build_career_sources()
for _key, _cls in CAREER_SOURCES.items():
    platform_registry.register(_key, _cls)

#: Every source key this package can actually serve.
IMPLEMENTED_KEYS: frozenset[str] = frozenset(
    [s.source_name for s in (*ALL_SOURCES, *UK_SOURCES)] + list(CAREER_SOURCES)
)

__all__ = [
    "ALL_SOURCES",
    "CAREER_SOURCES",
    "COMPANY_BOARDS",
    "IMPLEMENTED_KEYS",
    "UK_SOURCES",
    "AdzunaSource",
    "ApiJobSource",
    "ArbeitnowSource",
    "AshbySource",
    "AtsBoardSource",
    "CostType",
    "GreenhouseSource",
    "JobicySource",
    "LeverSource",
    "ReedSource",
    "RemoteOkSource",
    "RemotiveSource",
    "SmartRecruitersSource",
    "SourceUnavailableError",
]
