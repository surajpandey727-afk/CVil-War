"""Deterministic UK location policy: where is this job, and may a UK-based candidate do it?

The product only shows UK-relevant roles. Before this module the database stored a free-text
``location`` and nothing else, so "San Francisco, CA" and "London" were indistinguishable to
every query \u2014 which is how US and EU roles reached the jobs page.

Rules, in order of authority (strongest evidence wins, nothing is guessed):

1. **Explicit country text** in the posting's own location ("United Kingdom", "USA", "Remote -
   Canada", a US state, an ISO code such as "gb"/"us") decides that segment outright.
2. **A full UK postcode** ("EC4N 6EU", "M3 7FB") is UK.
3. **A known place**: a UK town or county, or a foreign city. A UK name with a famous foreign
   namesake ("Cambridge", "Birmingham") is only accepted bare when the source is UK-scoped.
4. **A UK-scoped source** (Reed, Adzuna /gb/, the UK visa boards) vouches for an otherwise
   unrecognised place name, because the upstream only returns UK jobs.

What is never used: the employer's headquarters, the posting's domain, the description's
language or currency. Those describe the company, not the job.

A multi-location posting ("Doha, Qatar; London, UK") is UK-eligible if any of its locations is
in the UK. Remote postings are UK-eligible only when the UK is explicitly among the countries
they hire in; "Remote", "Worldwide" or "EMEA" alone is *ambiguous* and quarantined, not shown.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.geo.gazetteer import (
    AMBIGUOUS_UK_PLACES,
    CA_PROVINCE_CODES,
    COUNTRIES,
    COUNTRY_NAMES,
    FOREIGN_CITIES,
    MACRO_REGIONS,
    POSTCODE_AREAS,
    UK_COUNTRY_TOKENS,
    UK_PLACES,
    UK_REGIONS,
    UK_SCOPED_SOURCES,
    US_STATE_CODES,
    US_STATES,
)

#: Verification outcomes. Only ``verified`` rows that are ``uk_eligible`` are shown by default.
VERIFIED = "verified"  # the country is established from the posting's own evidence
AMBIGUOUS = "ambiguous"  # evidence exists but does not settle the country
UNKNOWN = "unknown"  # no usable location evidence at all

ONSITE, HYBRID, REMOTE, UNSPECIFIED = "onsite", "hybrid", "remote", "unspecified"

#: A complete UK postcode (outward + inward code), spaced or not. Inward codes never contain
#: C, I, K, M, O or V, which is what keeps "SENIOR" or a US ZIP from matching.
_UK_POSTCODE = re.compile(r"^([a-z]{1,2})\d[a-z\d]? ?\d[abd-hjlnp-uw-z]{2}$")
_SEGMENT_SPLIT = re.compile("[;|\u2022\n]| \ufffd | or | and (?=remote)")
_PART_SPLIT = re.compile("[,/()\\[\\]\u2013\u2014]| - ")
#: "US-CA-Menlo Park", "GB-London", "Remote-EMEA": hyphen-joined codes, split only when the
#: piece starts that way so "Stoke-on-Trent" and "New-York" stay whole.
_CODE_PREFIX = re.compile(r"^(?:[a-z]{2}|remote)-")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_HAS_LATIN = re.compile(r"[a-z]{3}")
_PLACEHOLDERS = frozenset({"n a", "na", "location", "tbc", "tba", "various", "multiple locations"})

_REMOTE_WORDS = ("remote", "work from home", "home based", "homeoffice", "wfh", "anywhere")
_ONSITE_WORDS = ("on site", "onsite", "in office", "office based")
#: Words that decorate a place without naming one; stripped before lookups.
_NOISE = re.compile(
    r"\b(remote|hybrid|friendly|travel required|first|in the|based|hq|office|hub|job|"
    r"zentrale|only|or|and|of)\b"
)


@dataclass(frozen=True)
class LocationVerdict:
    """The normalised location fields stored on a job."""

    country_code: str | None
    country_name: str | None
    city: str | None
    region: str | None
    workplace_type: str
    remote_eligible_countries: list[str] = field(default_factory=list)
    status: str = UNKNOWN
    evidence: str = "none"

    @property
    def uk_eligible(self) -> bool:
        if self.status != VERIFIED:
            return False
        return self.country_code == "GB" or "GB" in self.remote_eligible_countries


@dataclass
class _Seg:
    countries: list[tuple[str, str]] = field(default_factory=list)  # (code, evidence)
    city: str | None = None
    region: str | None = None
    ambiguous_city: str | None = None
    macro: bool = False


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", _NON_WORD.sub(" ", folded.casefold())).strip()


def _parts(segment: str) -> list[str]:
    out: list[str] = []
    for piece in _PART_SPLIT.split(segment.casefold()):
        piece = piece.strip()
        subs = piece.split("-") if _CODE_PREFIX.match(piece) else [piece]
        out.extend(n for n in (_norm(s) for s in subs) if n)
    return out


def _strip_noise(part: str) -> str:
    return re.sub(r"\s+", " ", _NOISE.sub(" ", part)).strip()


def _lookup(c: str) -> tuple[str, str] | None:
    """What one normalised part names: ``(kind, value)`` or ``None``."""
    if c in UK_COUNTRY_TOKENS or c.startswith(("uk ", "united kingdom")):
        return "country", "GB"
    postcode = _UK_POSTCODE.match(c)
    if postcode:
        return "postcode", postcode.group(1)
    if c in COUNTRIES:
        return "country", COUNTRIES[c]
    if c in US_STATES or c in US_STATE_CODES:
        return "state", "US"
    if c in CA_PROVINCE_CODES:
        return "state", "CA"
    if c in UK_PLACES:
        return "uk_place", c
    if c in UK_REGIONS:
        return "uk_region", c
    if c in FOREIGN_CITIES:  # before ISO codes, so "SF" is San Francisco, not a country
        return "foreign_city", FOREIGN_CITIES[c]
    if len(c) == 2 and c.isalpha():  # an aggregator's lowercase ISO code: "Sydney, au"
        return "iso", c.upper()
    if c in MACRO_REGIONS:
        return "macro", c
    return None


def _country_word(part: str) -> tuple[str, str] | None:
    """Last resort for free text such as "Zilch UK" or "Mapbox Germany": a country named as a
    whole word. "us" is excluded \u2014 as a word it is far more often the pronoun."""
    for word in part.split():
        if word in ("uk", "england", "scotland", "wales", "britain"):
            return "country", "GB"
        if len(word) > 2 and word in COUNTRIES:
            return "country", COUNTRIES[word]
    return None


def _classify_segment(segment: str, *, uk_source: bool) -> _Seg:
    seg = _Seg()
    uk_places: list[str] = []
    foreign: str | None = None
    leftovers: list[str] = []
    for part in _parts(segment):
        bare = _strip_noise(part)
        hit = _lookup(part) or (_lookup(bare) if bare and bare != part else None)
        if hit is None:
            hit = _country_word(bare)
        if hit is None:
            if _HAS_LATIN.search(bare) and bare not in _PLACEHOLDERS:
                leftovers.append(bare)
            continue
        kind, value = hit
        if kind in ("country", "state", "iso"):
            seg.countries.append((value, "explicit_country" if kind != "state" else "us_state"))
        elif kind == "postcode":
            seg.countries.append(("GB", "uk_postcode"))
            seg.city = seg.city or POSTCODE_AREAS.get(value.upper())
        elif kind == "uk_place":
            uk_places.append(value)
        elif kind == "uk_region":
            seg.region = seg.region or value.title()
            seg.countries.append(("GB", "uk_region"))
        elif kind == "foreign_city":
            foreign = foreign or value
        else:
            seg.macro = True

    # The last place named is the town ("Frimley, Camberley"); the segment is ambiguous only
    # if every UK place in it has a foreign namesake.
    uk_place = uk_places[-1] if uk_places else ""
    ambiguous = all(p in AMBIGUOUS_UK_PLACES for p in uk_places)
    city, region = UK_PLACES.get(uk_place, (None, None))
    if seg.countries:
        # Explicit evidence settles the country; a UK place name only supplies the city when
        # that country is the UK ("London, ON" stays Canadian).
        if any(code == "GB" for code, _ in seg.countries):
            seg.city, seg.region = city or seg.city, seg.region or region
        return seg
    if uk_place and (uk_source or not ambiguous):
        seg.countries.append(("GB", "uk_place+uk_source" if uk_source else "uk_place"))
        seg.city, seg.region = city, region
    elif foreign:
        seg.countries.append((foreign, "foreign_city"))
    elif uk_place:  # a name with a famous foreign namesake, from a source not scoped to the UK
        seg.ambiguous_city = city
    elif leftovers and uk_source and not seg.macro:
        seg.countries.append(("GB", "uk_scoped_source"))
        seg.city = " ".join(w.capitalize() for w in leftovers[-1].split())
    return seg


def _workplace(text: str, remote_flag: bool) -> str:
    low = _norm(text)
    if "hybrid" in low:
        return HYBRID
    if remote_flag or any(w in low for w in _REMOTE_WORDS):
        return REMOTE
    if any(w in low for w in _ONSITE_WORDS):
        return ONSITE
    return UNSPECIFIED


def classify_location(
    location: str, *, remote: bool = False, platform: str = "", title: str = ""
) -> LocationVerdict:
    """Classify one job's location. Pure and deterministic: same input, same verdict."""
    uk_source = (platform or "").casefold() in UK_SCOPED_SOURCES
    raw = location or ""
    workplace = _workplace(f"{raw} {title}", remote)
    segments = [s for s in _SEGMENT_SPLIT.split(raw.casefold()) if s and s.strip()]
    results = [_classify_segment(s, uk_source=uk_source) for s in segments]

    meaningful = [r for r in results if r.countries or r.ambiguous_city or r.macro]
    blank = all(not _norm(s) or _norm(s) in _PLACEHOLDERS for s in segments)
    if not meaningful and uk_source and blank:
        # A UK-scoped board with no location text at all: the board's scope is the evidence.
        return _verdict("GB", None, None, workplace, [], VERIFIED, "uk_scoped_source")

    countries = list(dict.fromkeys(code for r in results for code, _ in r.countries))
    remote_countries = countries if workplace == REMOTE else []
    uk = next((r for r in results if any(code == "GB" for code, _ in r.countries)), None)
    if uk is not None:
        evidence = next(ev for code, ev in uk.countries if code == "GB")
        return _verdict("GB", uk.city, uk.region, workplace, remote_countries, VERIFIED, evidence)
    if countries:
        first = next(r for r in results if r.countries)
        code, evidence = first.countries[0]
        return _verdict(code, None, None, workplace, remote_countries, VERIFIED, evidence)
    amb = next((r for r in results if r.ambiguous_city), None)
    if amb is not None:
        return _verdict(None, amb.ambiguous_city, None, workplace, [], AMBIGUOUS, "ambiguous_place")
    if any(r.macro for r in results):
        return _verdict(None, None, None, workplace, [], AMBIGUOUS, "macro_region")
    return _verdict(None, None, None, workplace, [], UNKNOWN, "unrecognised" if raw else "none")


def _verdict(
    code: str | None,
    city: str | None,
    region: str | None,
    workplace: str,
    remote_countries: list[str],
    status: str,
    evidence: str,
) -> LocationVerdict:
    return LocationVerdict(
        country_code=code,
        country_name=COUNTRY_NAMES.get(code, code) if code else None,
        city=city,
        region=region,
        workplace_type=workplace,
        remote_eligible_countries=remote_countries,
        status=status,
        evidence=evidence,
    )
