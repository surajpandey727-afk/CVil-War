"""Job platform integrations with auto-registration.

Importing this package registers all built-in platform plugins
(LinkedIn, Indeed, Glassdoor) with the global ``platform_registry``.
"""

from app.core.automation.platforms.base import JobListing, JobPlatform
from app.core.automation.platforms.glassdoor import GlassdoorPlatform
from app.core.automation.platforms.indeed import IndeedPlatform
from app.core.automation.platforms.linkedin import LinkedInPlatform
from app.core.automation.platforms.registry import PlatformRegistry, platform_registry

# Auto-register all built-in platforms.
#
# NOTE: these three are currently NON-FUNCTIONAL — they route through
# core/automation/agent.py, which imports `BrowserConfig`, removed in browser-use 0.2
# (docs/PHASE0_AUDIT.md §4.3.1). Every search raises and is swallowed by job_search, so they
# contribute nothing. They stay registered so the failure stays visible in logs and so the
# apply-side code keeps its platform identifiers; working discovery comes from the keyless
# API sources in app.core.job_discovery.sources, registered below.
platform_registry.register("linkedin", LinkedInPlatform)
platform_registry.register("indeed", IndeedPlatform)
platform_registry.register("glassdoor", GlassdoorPlatform)

# Importing this package registers the API-backed sources (remotive, jobicy, arbeitnow,
# remoteok). Imported last to avoid a circular import: the sources subclass JobPlatform.
from app.core.job_discovery import sources as _api_sources  # noqa: E402,F401

__all__ = [
    "GlassdoorPlatform",
    "IndeedPlatform",
    "JobListing",
    "JobPlatform",
    "LinkedInPlatform",
    "PlatformRegistry",
    "platform_registry",
]
