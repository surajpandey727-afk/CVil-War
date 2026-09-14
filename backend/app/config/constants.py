"""Application-wide constants."""

# API version
API_V1_PREFIX = "/api/v1"

# Application version
APP_VERSION = "2.0.0"
APP_TITLE = "CVil-War"

# Queue names (Redis)
QUEUE_APPLY = "cvilwar:queue:apply"

# NOTE: status/purpose enums now live in app.models.enums (single source of truth).

# Supported platforms
# Keyless API sources — these are the ones that actually return results.
API_JOB_SOURCES = ["remotive", "jobicy", "arbeitnow", "remoteok", "movejobs", "tarve"]
# Browser-scraped platforms. Currently non-functional (docs/PHASE0_AUDIT.md §4.3.1) and kept
# only so the apply-side keeps its platform identifiers.
BROWSER_PLATFORMS = ["linkedin", "indeed", "glassdoor"]
# Default search fan-out. API sources lead: a default of the three browser platforms alone
# meant every search hit only the broken path and returned zero, regardless of what else was
# registered — the request default silently overrode the registry.
SUPPORTED_PLATFORMS = [*API_JOB_SOURCES, *BROWSER_PLATFORMS]

# Resume templates
RESUME_TEMPLATES = ["modern", "classic", "creative", "executive", "minimal"]

# Cover letter templates
COVER_LETTER_TEMPLATES = ["standard", "technical", "creative"]

# ATS scoring weights
ATS_WEIGHT_SKILLS = 0.4
ATS_WEIGHT_EXPERIENCE = 0.3
ATS_WEIGHT_EDUCATION = 0.2
ATS_WEIGHT_KEYWORDS = 0.1

# Pagination defaults
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
