"""Keyless API job sources, auto-registered with the shared platform registry.

Importing this package registers every adapter in :data:`boards.ALL_SOURCES`, so
``services.job_search`` picks them up through the same ``platform_registry`` it already uses
for the browser platforms — no change to the search service.
"""

from app.core.automation.platforms.registry import platform_registry
from app.core.job_discovery.sources.base import ApiJobSource
from app.core.job_discovery.sources.boards import (
    ALL_SOURCES,
    ArbeitnowSource,
    JobicySource,
    RemoteOkSource,
    RemotiveSource,
)

for _source in ALL_SOURCES:
    platform_registry.register(_source.source_name, _source)

__all__ = [
    "ALL_SOURCES",
    "ApiJobSource",
    "ArbeitnowSource",
    "JobicySource",
    "RemoteOkSource",
    "RemotiveSource",
]
