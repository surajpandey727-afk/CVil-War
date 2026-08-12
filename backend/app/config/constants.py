"""Application-wide constants."""

# API version
API_V1_PREFIX = "/api/v1"

# Application version
APP_VERSION = "2.0.0"
APP_TITLE = "AutoApply AI"

# Queue names (Redis)
QUEUE_APPLY = "autoapply:queue:apply"

# NOTE: status/purpose enums now live in app.models.enums (single source of truth).

# Supported platforms
SUPPORTED_PLATFORMS = ["linkedin", "indeed", "glassdoor"]

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
