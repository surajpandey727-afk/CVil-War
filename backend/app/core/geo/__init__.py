"""Location normalisation and the UK-only eligibility policy."""

from app.core.geo.classify import (
    AMBIGUOUS,
    UNKNOWN,
    VERIFIED,
    LocationVerdict,
    classify_location,
)

__all__ = ["AMBIGUOUS", "UNKNOWN", "VERIFIED", "LocationVerdict", "classify_location"]
