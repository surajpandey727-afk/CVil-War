"""Typed structured output for an apply run (browser-use ``output_model_schema``)."""

from pydantic import BaseModel


class ApplicationResult(BaseModel):
    """What the browser agent reports after attempting a submission."""

    submitted: bool = False
    confirmation_id: str | None = None
    status: str = ""
    notes: str = ""
