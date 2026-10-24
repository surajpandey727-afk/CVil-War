"""Posting dates are parsed from what sources publish, and never invented."""

from datetime import UTC, datetime

import pytest

from app.core.dates import parse_posted_at

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-01T09:30:00Z", datetime(2026, 10, 1, 9, 30, tzinfo=UTC)),
        ("2026-10-01T10:30:00+01:00", datetime(2026, 10, 1, 9, 30, tzinfo=UTC)),
        ("2026-10-01", datetime(2026, 10, 1, tzinfo=UTC)),
        ("01/10/2026", datetime(2026, 10, 1, tzinfo=UTC)),  # Reed: day-first, not US order
        ("Thu, 01 Oct 2026 09:30:00 +0000", datetime(2026, 10, 1, 9, 30, tzinfo=UTC)),
    ],
)
def test_published_formats_parse_to_utc(raw: str, expected: datetime) -> None:
    assert parse_posted_at(raw, now=NOW) == expected


@pytest.mark.parametrize(
    "raw", ["", None, "3 days ago", "Recently", "Just posted", "31/02/2026", "not a date"]
)
def test_unparseable_text_is_none_not_a_guess(raw: object) -> None:
    assert parse_posted_at(raw, now=NOW) is None


def test_future_dates_are_rejected() -> None:
    assert parse_posted_at("2027-01-01", now=NOW) is None


def test_placeholder_epoch_dates_are_rejected() -> None:
    assert parse_posted_at("1970-01-01T00:00:00Z", now=NOW) is None


def test_naive_timestamps_are_treated_as_utc() -> None:
    assert parse_posted_at("2026-10-01T09:30:00", now=NOW) == datetime(
        2026, 10, 1, 9, 30, tzinfo=UTC
    )
