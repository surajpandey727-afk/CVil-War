"""Best-effort classification of an inbound reply's content: rejection, interview invite, or
just "a reply" (everything else).

Rejection is checked before interview: a rejection email that also happens to mention
"interview" (e.g. "we've decided not to move forward after your interview") must not be
reported as an invite. This mirrors ``core.sponsorship.keywords``'s reasoning for checking
negations first — the more specific, more consequential signal wins ties.
"""

from __future__ import annotations

_REJECTION_PHRASES: tuple[str, ...] = (
    "unfortunately", "not moving forward", "not been successful", "unsuccessful",
    "decided not to proceed", "decided to move forward with other candidates",
    "will not be progressing", "other candidates whose", "pursue other candidates",
    "regret to inform", "not selected for this", "will not be moving your application",
    "wish you the best in your future", "wish you all the best in your job search",
)

_INTERVIEW_PHRASES: tuple[str, ...] = (
    "invite you to interview", "invited to interview", "schedule an interview",
    "schedule a call", "schedule a chat", "book a time to speak", "would like to speak with you",
    "next steps in the process", "move forward to the next stage", "phone screen",
    "technical interview", "interview with", "book an interview", "arrange an interview",
    "available for a call", "set up a call",
)


def classify(subject: str, snippet: str) -> str:
    """``"rejection"`` | ``"interview_invite"`` | ``"reply"`` from a message's own text.

    Never raises and never returns an empty string — an unclassifiable reply is still a
    reply, which is itself useful information the operator did not have before this synced.
    """
    haystack = f"{subject} {snippet}".casefold()
    if any(phrase in haystack for phrase in _REJECTION_PHRASES):
        return "rejection"
    if any(phrase in haystack for phrase in _INTERVIEW_PHRASES):
        return "interview_invite"
    return "reply"
