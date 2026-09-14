"""Typed structured output for an apply run (browser-use ``output_model_schema``)."""

from pydantic import BaseModel


class ApplicationResult(BaseModel):
    """What the browser agent reports after attempting a submission."""

    submitted: bool = False
    confirmation_id: str | None = None
    status: str = ""
    notes: str = ""
    #: True when the agent stopped because it hit a CAPTCHA, 2FA, or login wall it cannot
    #: pass unattended — a pause the operator can clear, not a failure. See the guardrail in
    #: ``runtime.apply`` and ``workers.tasks._mark_needs_verification``.
    blocked: bool = False
    blocked_reason: str = ""
