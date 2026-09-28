"""Turn the salary line a job board publishes into a number you can filter on.

Job boards publish pay as free text and nothing else: ``"£90,000 - £110,000"``,
``"Up to £60,000 + 10% bonus"``, ``"£500 per day outside IR35"``, ``"Competitive"``. A filter
needs an amount, so something has to read that text, and the naive version of that -- take the
smallest number in the string -- is wrong on most real postings rather than a few unusual ones:

    "Up to £60,000 + 10% bonus"        -> 10       (the bonus percentage)
    "£65,000 per annum, 25 days holiday" -> 25     (the holiday allowance)
    "£500 per day"                     -> 500,000  (a day rate read as an annual figure)

Each of those makes the filter lie in the direction that costs the candidate a role: a "minimum
£50k" search hid a £60k job and kept a £25k one. This module exists so there is exactly one
answer to "what does this posting pay", used by the API response, the filters and the cards
alike, instead of three parsers that disagree.

Nothing here guesses. A string with no recoverable amount returns an empty band, which the UI
renders as "not published" -- a different fact from "£0", and one the candidate needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Working days per year: 5 days x 52 weeks, less 25 days leave and 8 bank holidays. Contract
#: day rates are quoted against billable days, so a flat 365 or 260 overstates them badly.
DAYS_PER_YEAR = 220
#: 37.5-hour week over the same 44 billable weeks.
HOURS_PER_YEAR = 1650
MONTHS_PER_YEAR = 12

#: Below this, an "annual" figure is not a salary -- it is a fee, a bonus or a typo.
_MIN_CREDIBLE_ANNUAL = 8_000
#: Above this it is a budget, a share price or a mis-parsed identifier.
_MAX_CREDIBLE_ANNUAL = 2_000_000

_CURRENCY_BY_SYMBOL = {"£": "GBP", "$": "USD", "€": "EUR"}
_CURRENCY_CODES = ("GBP", "USD", "EUR")

#: Fragments that contain a number which is definitely not pay. Removed before any amount is
#: read, because the alternative -- reading them and hoping the ranking sorts it out -- is
#: exactly how a holiday allowance became a salary.
_NOT_MONEY = re.compile(
    r"""
    \d+(?:\.\d+)?\s*%                      # 10% bonus, 5% pension
    | \bir\s*35\b                          # "outside IR35"
    | \btier\s*\d\b                        # visa tier
    | \d+\s*(?:days?|weeks?|months?|years?|yrs?|hrs?|hours?)['\u2019]?\s*
      (?:of\s+)?
      (?:holiday|leave|annual\s+leave|notice|experience|exp\b|per\s+week|a\s+week|in\s+office|onsite|on-site|remote|probation)
    """,
    # No rule for a bare year: nothing that looks like one clears the credibility floor, and a
    # rule matching "2000" would have deleted the amount out of "£2000 per month".
    re.IGNORECASE | re.VERBOSE,
)

#: An amount: an optional symbol, digits with optional thousands separators, an optional
#: ``k``. ``85k``, ``£85,000``, ``USD 120000`` and ``€80.000`` all match.
_AMOUNT = re.compile(
    r"(?P<sym>[£$€])?\s*(?P<num>\d{1,3}(?:[,\s]\d{3})+|\d+(?:\.\d+)?)\s*(?P<k>k\b)?",
    re.IGNORECASE,
)

_PERIODS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("hour", re.compile(r"\b(?:per\s+hour|hourly|an?\s+hour|/\s*h(?:r|our)?\b|\bp\.?h\b)", re.I)),
    ("day", re.compile(r"\b(?:per\s+day|daily|a\s+day|day\s+rate|/\s*day\b|\bp\.?d\b)", re.I)),
    ("month", re.compile(r"\b(?:per\s+month|monthly|a\s+month|/\s*month\b|\bpcm\b)", re.I)),
    (
        "year",
        re.compile(r"\b(?:per\s+annum|per\s+year|annually|yearly|/\s*year\b|\bp\.?a\b)", re.I),
    ),
)

_UP_TO = re.compile(r"\b(?:up\s+to|max(?:imum)?\s+of|no\s+more\s+than|to\s+a\s+max)", re.I)
# Deliberately not "OTE": on-target earnings is a total including commission, not a floor.
_FROM = re.compile(r"\b(?:from|starting\s+(?:at|from)|min(?:imum)?\s+of|upwards\s+of)", re.I)


@dataclass(frozen=True)
class SalaryBand:
    """A posting's pay, annualised, or empty when the posting did not publish one."""

    minimum: int | None = None
    maximum: int | None = None
    currency: str | None = None
    #: The period the posting quoted. ``"year"`` unless it advertised a day or hourly rate.
    period: str | None = None
    #: True when ``minimum``/``maximum`` were converted from a day, hour or monthly rate.
    #: A £500 day rate becomes £110,000, which is a fair comparison but not a quoted figure,
    #: and the UI says so rather than presenting it as the employer's own number.
    annualised: bool = False

    @property
    def published(self) -> bool:
        return self.minimum is not None or self.maximum is not None


EMPTY = SalaryBand()


def _period(text: str) -> str | None:
    for name, pattern in _PERIODS:
        if pattern.search(text):
            return name
    return None


def _currency(text: str) -> str | None:
    for symbol, code in _CURRENCY_BY_SYMBOL.items():
        if symbol in text:
            return code
    upper = text.upper()
    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", upper):
            return code
    return None


def _annualise(value: float, period: str | None) -> float:
    if period == "day":
        return value * DAYS_PER_YEAR
    if period == "hour":
        return value * HOURS_PER_YEAR
    if period == "month":
        return value * MONTHS_PER_YEAR
    return value


def parse_salary(raw: str | None) -> SalaryBand:
    """Read a published salary line into an annualised band.

    Returns :data:`EMPTY` for anything with no recoverable amount, including the very common
    ``"Competitive"`` and ``"DOE"``. That is deliberately not ``0``: a filter that treats an
    unpublished salary as zero excludes every job that does not advertise pay, which on most
    UK boards is the majority of them.
    """
    if not raw or not raw.strip():
        return EMPTY

    text = raw.strip()
    period = _period(text)
    currency = _currency(text)

    # Strip the fragments whose numbers are not pay before reading any amount. Doing this
    # first is what separates "£60,000 + 10% bonus" from "£10,000".
    cleaned = _NOT_MONEY.sub(" ", text)

    values: list[float] = []
    for match in _AMOUNT.finditer(cleaned):
        digits = match.group("num").replace(",", "").replace(" ", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        has_k = bool(match.group("k"))
        if has_k:
            value *= 1000
        # An amount has to look like money: attached to a currency symbol, carrying a `k`, or
        # simply large. A bare "5" in "5 stage interview" is none of those.
        if not (match.group("sym") or has_k or value >= 1000 or (currency and value >= 100)):
            continue
        values.append(value)

    if not values:
        return EMPTY

    annual = sorted(_annualise(v, period) for v in values)
    credible = [v for v in annual if _MIN_CREDIBLE_ANNUAL <= v <= _MAX_CREDIBLE_ANNUAL]
    if not credible:
        return EMPTY

    if len(credible) == 1:
        only = credible[0]
        # "Up to £60,000" states a ceiling and no floor; "from £60,000" the reverse. Recording
        # one as though it were both is how a "from £60k" role gets excluded by a £70k ceiling
        # it might well clear.
        if _UP_TO.search(text):
            low, high = None, only
        elif _FROM.search(text):
            low, high = only, None
        else:
            low, high = only, only
    else:
        low, high = credible[0], credible[-1]

    return SalaryBand(
        minimum=round(low) if low is not None else None,
        maximum=round(high) if high is not None else None,
        currency=currency,
        period=period or "year",
        annualised=period in {"day", "hour", "month"},
    )
