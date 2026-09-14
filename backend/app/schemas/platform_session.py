"""Schemas for importing and listing per-user platform browser sessions."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from app.config.constants import SUPPORTED_PLATFORMS


class PlatformSessionImport(BaseModel):
    """A captured browser ``storage_state`` (Playwright shape) to persist for a platform."""

    platform: str
    storage_state: dict[str, Any]
    expires_at: datetime | None = None

    @field_validator("platform")
    @classmethod
    def _known_platform(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in SUPPORTED_PLATFORMS:
            raise ValueError(
                f"Unsupported platform '{v}'. Supported: {', '.join(SUPPORTED_PLATFORMS)}"
            )
        return normalized

    @field_validator("storage_state")
    @classmethod
    def _has_cookies(cls, v: dict[str, Any]) -> dict[str, Any]:
        cookies = v.get("cookies")
        if not isinstance(cookies, list) or not cookies:
            raise ValueError(
                "storage_state must include a non-empty 'cookies' list (a Playwright storage_state)"
            )
        return v


class PlatformSessionResponse(BaseModel):
    """Public, cookie-free view of a stored platform session."""

    platform: str
    connected: bool = True
    last_verified_at: datetime | None = None
    expires_at: datetime | None = None


class ConnectStart(BaseModel):
    """Request to open a login window for a platform."""

    platform: str

    @field_validator("platform")
    @classmethod
    def _connectable(cls, v: str) -> str:
        # Validated against the source registry rather than a hand-kept constant, so a portal
        # added to the catalogue is connectable immediately instead of after someone
        # remembers to extend a second list.
        from app.core.automation.connect import connectable

        normalized = v.strip().lower()
        if not connectable(normalized):
            raise ValueError(
                f"'{v}' is not a portal a browser session can be connected for. "
                "Only portals with an authenticated-browser mechanism can be connected."
            )
        return normalized


class ConnectAttemptResponse(BaseModel):
    """Progress of an interactive login capture. Never carries cookies or credentials."""

    id: str
    platform: str
    state: str
    #: True once the session is stored; the UI stops polling here.
    done: bool
    #: What the operator should do right now, or what happened.
    instructions: str = ""
    detail: str = ""
    seconds_remaining: int = 0
