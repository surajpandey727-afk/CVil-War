"""Parse the posting dates job sources publish, without ever inventing one.

Sources publish dates in a handful of shapes: ISO-8601 timestamps (Greenhouse, Adzuna), bare
ISO dates (LinkedIn's ``<time datetime>``), UK day-first dates (Reed: ``24/10/2026``) and RFC
2822 (RSS feeds). Anything else — "3 days ago", "Recently", an empty string — returns ``None``
and the UI says "Posting date unavailable". Estimating a date from relative text, from when we
happened to discover the job, or from an LLM would be fabricating evidence.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

_DAY_FIRST = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
#: Earliest plausible posting date. Older values are placeholders (epoch zero, 1900-01-01).
_FLOOR = datetime(2000, 1, 1, tzinfo=UTC)
#: Clock-skew allowance: a source's timestamp may be a little ahead of ours, never days.
_FUTURE_SLACK = timedelta(days=1)


def parse_posted_at(value: object, *, now: datetime | None = None) -> datetime | None:
    """A timezone-aware UTC datetime for a source's posting date, or ``None``."""
    if isinstance(value, datetime):
        parsed: datetime | None = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        parsed = _parse_text(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    current = now or datetime.now(UTC)
    if parsed < _FLOOR or parsed > current + _FUTURE_SLACK:
        return None
    return parsed


def _parse_text(text: str) -> datetime | None:
    day_first = _DAY_FIRST.match(text)
    if day_first:
        day, month, year = (int(g) for g in day_first.groups())
        try:
            return datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            return None
    iso = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
