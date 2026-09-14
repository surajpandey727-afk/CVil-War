"""Apollo.io: log a recruiter contact against an application.

Deliberately scoped to logging only, not launching outreach sequences. Apollo's sequence API
(``emailer_campaigns``) sends real email from a real connected mailbox and requires a sequence
and a sender mailbox to already exist in the operator's own Apollo account — assuming either
would be inventing state that is not this system's to invent, and getting it wrong would send
an email nobody reviewed. Logging a contact is unconditionally safe (Apollo's own API treats
it as an upsert with no side effect on any real person) and is the piece that actually needs
automating: capturing "I reached out to this recruiter" the moment it happens, rather than the
operator remembering to do it by hand later in Apollo's own UI.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from app.config.settings import get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.apollo.io/v1"
_TIMEOUT = 15.0


class ApolloNotConfiguredError(Exception):
    """No Apollo API key is set — see ``APOLLO_API_KEY`` in ``.env``."""


@dataclass(frozen=True)
class ApolloContactResult:
    """What logging a contact actually produced, for the timeline entry to cite."""

    contact_id: str | None
    matched_existing: bool


def _require_api_key() -> str:
    key = get_settings().apollo_api_key.get_secret_value()
    if not key:
        raise ApolloNotConfiguredError(
            "No Apollo API key is configured. Set APOLLO_API_KEY in .env, then restart."
        )
    return key


async def log_contact(
    *,
    email: str,
    first_name: str = "",
    last_name: str = "",
    organization_name: str = "",
    title: str = "",
) -> ApolloContactResult:
    """Create (or, per Apollo's own upsert behaviour, update) a contact in Apollo.

    Raises ``ApolloNotConfiguredError`` if no key is set, and re-raises ``httpx.HTTPStatusError``
    on a real API failure (bad key, rate limit) — the caller decides how to surface that to the
    operator rather than this silently swallowing a failed log as a successful one.
    """
    api_key = _require_api_key()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f"{_BASE_URL}/contacts",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json={
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "organization_name": organization_name,
                "title": title,
                "label_names": ["CVil-War"],
            },
        )
        response.raise_for_status()
        body = response.json()

    contact = body.get("contact") or {}
    contact_id = contact.get("id")
    # Apollo upserts on email/details match rather than erroring on a duplicate; the response
    # carries no explicit "was this new" flag, so this is inferred from whether the contact
    # already had an id-bearing history (`contact_emails` populated on an existing record is
    # the closest available signal) — best-effort, and only used for the timeline's wording.
    matched_existing = bool(contact.get("contact_emails"))
    logger.info("apollo.contact_logged", contact_id=contact_id, organization=organization_name)
    return ApolloContactResult(contact_id=contact_id, matched_existing=matched_existing)
