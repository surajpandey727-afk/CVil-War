"""Strict location matching for job listings already in the database.

This is deliberately **not** the same matcher as
:func:`app.core.job_discovery.sources.base.matches_location`, and the difference is the point.

* That one runs during **discovery**, deciding whether to keep a listing an upstream board
  returned. It is generous on purpose: a false negative there silently loses a real job the
  operator will never see, so "London" accepts UK-wide and Europe-remote postings.
* This one runs when the operator **filters a list they are looking at**. Here the failure
  mode is reversed. Asking for London and getting a Cleveland accounts-payable role is what
  makes the filter worthless, so the same generosity is a bug.

Two matchers, two jobs. Loosening this one to match the other would put the commuter-belt
noise straight back into the results; tightening the other would drop real jobs at discovery
time, where nothing can recover them.

The city table is data, not code paths: adding a city means adding an entry, and the filter
keeps working for jobs imported later because it matches on the stored ``Job.location`` text
rather than on any fixed list of job ids.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The 32 London boroughs, the City of London, and the districts that routinely appear in
#: job adverts instead of a borough name. A posting saying "Canary Wharf" is a London job;
#: refusing it because the advert never wrote the word "London" is the same false negative
#: this module exists to avoid — just one level further down.
_LONDON_AREAS = frozenset({
    "london", "greater london", "central london", "city of london", "east london",
    "west london", "north london", "south london", "barking", "dagenham", "barnet",
    "bexley", "brent", "bromley", "camden", "croydon", "ealing", "enfield", "greenwich",
    "hackney", "hammersmith", "fulham", "haringey", "harrow", "havering", "hillingdon",
    "hounslow", "islington", "kensington", "chelsea", "kingston upon thames", "lambeth",
    "lewisham", "merton", "newham", "redbridge", "richmond upon thames", "southwark",
    "sutton", "tower hamlets", "waltham forest", "wandsworth", "westminster",
    "canary wharf", "shoreditch", "soho", "holborn", "paddington", "stratford",
    "clerkenwell", "mayfair", "shepherds bush", "white city", "kings cross",
})

#: Terms that describe a country or a region, never a city. A job whose whole location is one
#: of these is *not* established as a London job, and treating it as one is exactly how "UK"
#: postings flooded a London search.
_COUNTRY_WIDE = frozenset({
    "uk", "u.k.", "united kingdom", "gb", "great britain", "britain", "england", "scotland",
    "wales", "northern ireland", "europe", "emea", "eu", "worldwide", "global", "anywhere",
    "remote", "remote uk", "uk remote", "uk wide", "nationwide", "multiple locations",
    "various", "various locations", "home based", "work from home", "hybrid",
})

#: Postcode districts. London's outward codes are distinctive enough to identify a job whose
#: advert gives only a postcode — Reed does this constantly ("EC4N6EU").
#:
#: The trailing inward code is optional but must be allowed to run straight on: real Reed
#: values arrive unspaced, and requiring a word boundary after the outward code alone made
#: "EC4N6EU" fail to match while the spaced "EC4N 6EU" passed.
_LONDON_POSTCODE = re.compile(
    r"\b(?:EC|WC|NW|SE|SW|N|E|W)\d{1,2}[A-Z]?(?:\s*\d[A-Z]{2})?\b", re.IGNORECASE
)
#: Anchored so "SE1" matches but "SENIOR" does not, and so a non-London outward code such as
#: "M1" (Manchester) or "B15" (Birmingham) is never picked up.
_NON_LONDON_PREFIXES = frozenset({"M", "B", "L", "S", "G", "CF", "BS", "LS", "NE", "OX", "CB"})


@dataclass(frozen=True)
class City:
    """One filterable place, with everything that legitimately names it."""

    key: str
    label: str
    #: Names and districts that identify this city.
    areas: frozenset[str]
    #: Optional postcode recogniser for adverts that give only a code.
    postcode: re.Pattern[str] | None = None
    aliases: frozenset[str] = field(default_factory=frozenset)


CITIES: tuple[City, ...] = (
    City(
        key="london",
        label="London",
        areas=_LONDON_AREAS,
        postcode=_LONDON_POSTCODE,
        aliases=frozenset({"london uk", "london england", "london gb", "ldn"}),
    ),
    City(key="manchester", label="Manchester", areas=frozenset({"manchester", "salford"})),
    City(key="birmingham", label="Birmingham", areas=frozenset({"birmingham"})),
    City(key="edinburgh", label="Edinburgh", areas=frozenset({"edinburgh"})),
    City(key="glasgow", label="Glasgow", areas=frozenset({"glasgow"})),
    City(key="bristol", label="Bristol", areas=frozenset({"bristol"})),
    City(key="leeds", label="Leeds", areas=frozenset({"leeds"})),
    City(key="cambridge", label="Cambridge", areas=frozenset({"cambridge"})),
    City(key="oxford", label="Oxford", areas=frozenset({"oxford"})),
    City(key="dublin", label="Dublin", areas=frozenset({"dublin"})),
)

_BY_KEY = {c.key: c for c in CITIES}

#: Splits a location string into its parts. Adverts use commas, slashes, pipes, brackets and
#: dashes more or less interchangeably. The dashes are given as escapes rather than literals
#: so the pattern stays unambiguous in a source file that is otherwise plain ASCII.
_SEPARATORS = re.compile("[,/|()\\[\\]\u2013\u2014]| - ")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def _normalise(text: str) -> str:
    return _NON_WORD.sub(" ", (text or "").casefold()).strip()


def _parts(location: str) -> list[str]:
    """The distinct place-name fragments of a location string, normalised."""
    return [p for p in (_normalise(part) for part in _SEPARATORS.split(location or "")) if p]


def resolve_city(requested: str) -> City | None:
    """Which known city the operator's filter text refers to, if any.

    Returns ``None`` for free text that is not a city we can filter precisely — a country, a
    region, or somewhere not in the table. The caller then falls back to a substring match
    rather than silently returning nothing, because refusing to filter is better than
    filtering wrongly and better than showing an empty list.
    """
    text = _normalise(requested)
    if not text:
        return None
    for city in CITIES:
        if text == city.key or text in city.aliases or text in city.areas:
            return city
        # "London, UK" and "London England" arrive as one string from the search box.
        if any(part in city.areas or part == city.key for part in _parts(requested)):
            return city
    return None


def _postcode_is_london(location: str, pattern: re.Pattern[str]) -> bool:
    """True if the advert carries a London outward postcode.

    Guards against other cities' codes sharing a shape: "M1" and "B15" match the generic
    letter-digit form, so any code whose letters name a non-London area is rejected outright.
    """
    for match in pattern.finditer(location or ""):
        letters = re.match(r"[A-Za-z]+", match.group(0))
        if letters and letters.group(0).upper() in _NON_LONDON_PREFIXES:
            continue
        return True
    return False


def matches_city(city: City, job_location: str, *, remote: bool = False) -> bool:
    """True if a stored job's location genuinely places it in ``city``.

    ``remote`` is accepted but not treated as a match on its own. A fully remote role that
    names no city is not a London job, and counting it as one is what the operator is
    complaining about — they filtered for London and got Worldwide postings. A role that is
    *both* remote and names the city ("Remote — London") does match, on the strength of the
    city, not the remoteness.
    """
    parts = _parts(job_location)
    if not parts:
        return False

    # Any fragment naming the city or one of its districts is decisive.
    if any(part in city.areas or part == city.key for part in parts):
        return True

    # A multi-word fragment can still contain the city ("greater london area").
    if any(area in part for part in parts for area in city.areas if " " in area):
        return True

    # Postcode-only adverts, where nothing spells the city out.
    return bool(city.postcode) and _postcode_is_london(job_location, city.postcode)


def is_country_wide(job_location: str) -> bool:
    """True when a location says only 'UK', 'Remote', 'Europe' or similar.

    These are the postings that must NOT satisfy a city filter. They are excluded explicitly
    rather than by failing to match, so the intent is testable and a future alias added to a
    city cannot accidentally start capturing them.
    """
    parts = _parts(job_location)
    return bool(parts) and all(part in _COUNTRY_WIDE for part in parts)


def location_matches(requested: str, job_location: str, *, remote: bool = False) -> bool:
    """Does a stored job satisfy the operator's location filter?

    Three cases, in order:

    1. **A known city** — matched precisely, with country-wide postings excluded.
    2. **A country or region** ("UK", "Europe") — matched loosely on substring, since the
       operator has explicitly asked for something broad.
    3. **Anything else** — substring match, so an unusual place name still filters something
       rather than returning nothing at all.
    """
    if not (requested or "").strip():
        return True

    city = resolve_city(requested)
    if city is not None:
        if is_country_wide(job_location):
            return False
        return matches_city(city, job_location, remote=remote)

    needle = _normalise(requested)
    haystack = _normalise(job_location)
    return bool(needle) and needle in haystack


def city_label(key: str) -> str:
    """Display name for a city key, or the key itself if it is not in the table."""
    city = _BY_KEY.get(key)
    return city.label if city else key
