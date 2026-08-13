"""Wire format for the application evidence panel.

Every section carries a ``recorded`` flag. That is the whole contract with the UI: a section
that was never captured is reported as absent rather than as empty, so the panel can print
"Not recorded" instead of a blank that reads like a fact. A historical application has no
account and no logs, and pretending otherwise is worse than saying so.

Nothing here exposes a credential. The account section carries a masked label and a
connection state; passwords, cookies and tokens are never read on this path.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EvidenceJob(BaseModel):
    """The posting this application was made against."""

    recorded: bool = True
    job_id: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    salary: str | None = None
    remote: bool = False
    #: The board the application lives on: reed, linkedin, careers:monzo, …
    source: str | None = None
    #: Where the advert is. ``None`` means no URL was stored — the UI must say so rather
    #: than construct one.
    job_url: str | None = None
    #: Where the form is, and only when it genuinely differs from ``job_url``.
    application_url: str | None = None
    posted_at: datetime | None = None


class EvidenceSubmission(BaseModel):
    """What was sent, how, and whether anything confirmed it."""

    status: str
    #: ``None`` on an already-sent application means the row predates run recording.
    method: str | None = None
    confirmation_state: str
    #: The agent's own words. Shown verbatim — a paraphrase of a confirmation is not one.
    confirmation_detail: str | None = None
    external_reference: str | None = None
    submitted_at: datetime | None = None
    ats_score: float | None = None
    apply_mode: str
    origin: str
    #: Who did it: ``agent``, ``you``, or unknown.
    actor: str | None = None
    recorded: bool = True


class EvidenceDocument(BaseModel):
    """The exact CV attached at submission."""

    recorded: bool = True
    document_id: str | None = None
    name: str | None = None
    #: base / tailored / optimized.
    kind: str | None = None
    ats_score: float | None = None
    created_at: datetime | None = None
    #: Archived CVs stay attached — that is why archiving exists instead of deletion.
    archived: bool = False
    has_pdf: bool = False
    has_docx: bool = False


class EvidenceCoverLetter(BaseModel):
    """Whether a letter went with it."""

    recorded: bool = True
    used: bool = False
    name: str | None = None
    #: ``generated`` where that can be told from where the file lives; otherwise unset
    #: rather than guessed.
    origin: str | None = None


class EvidenceAccount(BaseModel):
    """Which login the submission went through. Safe metadata only."""

    recorded: bool = True
    platform: str | None = None
    #: Masked, e.g. ``sur***@example.com``. Never a full address, never a credential.
    account: str | None = None
    connected: bool = False
    state: str | None = None
    detail: str | None = None
    last_used_at: datetime | None = None


class EvidenceLogEntry(BaseModel):
    """One line of real execution history."""

    at: datetime
    #: ``application`` (lifecycle timeline) or ``automation`` (browser agent steps).
    source: str
    kind: str
    message: str
    detail: str | None = None
    actor: str | None = None


class EvidenceFailure(BaseModel):
    """Why a failed application failed."""

    message: str
    failure_class: str | None = None
    root_cause: str | None = None
    failed_at: datetime | None = None
    url: str | None = None
    step_count: int | None = None
    #: Only true where re-queueing is genuinely supported, so the UI never shows a retry
    #: button that does nothing.
    can_retry: bool = False


class ApplicationEvidence(BaseModel):
    """Everything needed to prove what happened to one application."""

    application_id: str
    job: EvidenceJob
    submission: EvidenceSubmission
    resume: EvidenceDocument
    cover_letter: EvidenceCoverLetter
    account: EvidenceAccount
    failure: EvidenceFailure | None = None
    log: list[EvidenceLogEntry] = Field(default_factory=list)
    #: False when nothing was ever logged for this application, which is different from a
    #: run that logged nothing interesting.
    log_recorded: bool = False
