"""Single entry point combining the register and keyword signals into one stamp per job.

Called once per discovered listing (``services.job_search._listing_to_job``), regardless of
which source found it — the same classification logic applies to every board uniformly, which
is the whole point of doing it here rather than per-adapter.
"""

from __future__ import annotations

from app.core.sponsorship import keywords, register
from app.models.enums import SponsorConfidence


def classify(company: str, description: str) -> tuple[SponsorConfidence, str | None]:
    """``(confidence, evidence)`` for one posting. ``evidence`` is ``None`` for UNKNOWN —
    there is nothing to show, which is different from a fact that was hidden.

    A register match wins even over the posting's own explicit "no sponsorship" text — the
    Home Office register is the stronger, independently-verified signal, and a licensed
    sponsor's own careers-page boilerplate is a common source of exactly this false negative
    (e.g. a generic disclaimer left over from a different role's requirements).
    """
    match = register.is_registered_sponsor(company)
    if match.matched:
        route_note = " (Skilled Worker route)" if match.skilled_worker_route else ""
        return (
            SponsorConfidence.CONFIRMED_REGISTER,
            f"Licensed sponsor: {match.matched_name}{route_note}",
        )

    detected, phrase = keywords.detect(description)
    if detected:
        return SponsorConfidence.KEYWORD_DETECTED, f'Posting states: "{phrase}"'

    negated, negation_phrase = keywords.detect_negation(description)
    if negated:
        return SponsorConfidence.NOT_SPONSOR, f'Posting states: "{negation_phrase}"'

    return SponsorConfidence.UNKNOWN, None
