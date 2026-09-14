"""Schemas for the Communications surface: Gmail connection state, sync results, the feed."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GmailStatus(BaseModel):
    """Whether Gmail reply-detection is set up at all, and connected for this operator."""

    configured: bool  # a Google Cloud OAuth client is set in .env
    connected: bool  # this operator has completed the one-time consent flow
    authorize_url: str | None = None  # present only when configured and not yet connected


class InboxSyncResponse(BaseModel):
    fetched: int
    already_seen: int
    matched_to_application: int
    unmatched: int
    errors: list[str]


class ApolloStatus(BaseModel):
    configured: bool  # an Apollo API key is set in .env


class LogRecruiterContactRequest(BaseModel):
    email: str
    first_name: str = ""
    last_name: str = ""
    title: str = ""


class LogRecruiterContactResponse(BaseModel):
    contact_id: str | None
    matched_existing: bool


class CommunicationEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    application_id: str | None = None
    sender: str
    subject: str
    snippet: str
    occurred_at: datetime
    matched_confidence: float
    classified_as: str


class CommunicationEventListResponse(BaseModel):
    items: list[CommunicationEventItem]
    total: int
    unmatched: int


class LinkApplicationRequest(BaseModel):
    application_id: str
