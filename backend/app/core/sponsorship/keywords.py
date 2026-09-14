"""Explicit visa-sponsorship language in a job posting's own text.

Weaker evidence than a register match (:mod:`register`) — a listing can truthfully omit
sponsorship language even when the employer sponsors, and "sponsor" appears in enough
unrelated contexts (event sponsorship, sponsored content) that a bare substring match is not
safe. Negations are checked first so "no visa sponsorship available" is never reported as a
positive signal just because it also contains "sponsorship available".
"""

from __future__ import annotations

_PHRASES: tuple[str, ...] = (
    "visa sponsorship available",
    "visa sponsorship is available",
    "sponsorship available",
    "can sponsor",
    "will sponsor",
    "able to sponsor",
    "happy to sponsor",
    "sponsor a visa",
    "sponsor your visa",
    "sponsor applicants",
    "sponsor candidates",
    "skilled worker route",
    "skilled worker visa",
    "certificate of sponsorship",
    "uk skilled worker visa",
    "we sponsor",
    "this role is eligible for sponsorship",
    "visa sponsorship provided",
)

_NEGATIONS: tuple[str, ...] = (
    "no visa sponsorship",
    "not offer visa sponsorship",
    "unable to sponsor",
    "cannot sponsor",
    "can not sponsor",
    "does not sponsor",
    "do not sponsor",
    "not able to sponsor",
    "sponsorship is not available",
    "no sponsorship available",
    "not provide sponsorship",
    "without sponsorship",
    "we do not offer sponsorship",
)


def detect(text: str) -> tuple[bool, str]:
    """``(detected, matched_phrase)`` from free text (job description, requirements, etc.).

    A negation anywhere in the text suppresses every positive match — a posting explaining
    "no visa sponsorship available for this role" almost always also uses the word "visa"
    elsewhere, and treating the two independently would report it as sponsoring.
    """
    haystack = (text or "").casefold()
    if not haystack:
        return False, ""
    for negation in _NEGATIONS:
        if negation in haystack:
            return False, ""
    for phrase in _PHRASES:
        if phrase in haystack:
            return True, phrase
    return False, ""


def detect_negation(text: str) -> tuple[bool, str]:
    """``(detected, matched_phrase)`` for an explicit *no*-sponsorship statement.

    Distinct from a plain absence of sponsorship language: this only fires when the posting
    itself states it does not sponsor, which is stronger, actionable evidence for a candidate
    who specifically needs sponsorship — not merely "this posting didn't happen to mention it".
    """
    haystack = (text or "").casefold()
    if not haystack:
        return False, ""
    for negation in _NEGATIONS:
        if negation in haystack:
            return True, negation
    return False, ""
