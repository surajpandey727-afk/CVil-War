"""The UK Home Office's public register of licensed Skilled Worker sponsors.

Downloaded from the register's gov.uk publication page rather than a hardcoded CSV URL: the
Home Office republishes the file regularly under a new dated filename
(``..._Web_Register_-_YYYY-MM-DD.csv``), so a fixed URL goes stale within days. This reads the
publication page's HTML to find whichever link is current, matching the same
``PUBLIC_WEBSITE``-mechanism reasoning already used for the keyless job-board adapters in
``core.job_discovery.sources``.

The cached copy is what every lookup actually reads (:func:`is_registered_sponsor` never makes
a network call) — refreshing it is a separate, explicit step, run by the weekly
``workers.tasks.refresh_sponsor_register`` cron or the settings-page "Refresh" action.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

from app.core.job_discovery.dedup import (
    companies_match,
    company_bucket,
    normalise_company,
)

logger = structlog.get_logger(__name__)

PUBLICATION_URL = (
    "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
)
_CSV_LINK_RE = re.compile(r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"')

# Same reasoning as app.services.resume.UPLOAD_DIR: a project-relative path lives inside the
# read-only deployment bundle on Vercel. Unlike that scratch space, this cache is meant to
# persist across requests — /tmp doesn't survive a cold start, so a serverless deployment
# re-downloads the (public, freely re-fetchable) register more often than STALE_AFTER_DAYS
# implies, a real but acceptable cost against the alternative of crashing on every refresh.
_DATA_DIR = Path(tempfile.gettempdir()) / "cvilwar-reference"
_CSV_PATH = _DATA_DIR / "sponsors_register.csv"
_META_PATH = _DATA_DIR / "sponsors_register.meta.json"

#: A cached copy is treated as fresh for this long. The register does not change hour to
#: hour, and re-downloading a ~140k-row, several-MB file on every settings-page load would be
#: pointless load on gov.uk for no benefit — the weekly cron is what actually keeps it current.
STALE_AFTER_DAYS = 7

_ROUTE_SKILLED_WORKER = "skilled worker"

#: Words that describe a legal entity's jurisdiction/function rather than distinguish it
#: from another company — "Amazon UK Services" is still Amazon; "Amazon Filters" or "Amazon
#: Charitable Trust" are not. Deliberately small and conservative: this only ever *prefers*
#: one containment match over another (see `lookup`'s `_rank`), it never turns a match into
#: a non-match, so a false negative here costs nothing beyond falling back to the
#: fewest-extra-words tie-break that already existed.
_GENERIC_DESCRIPTORS = frozenset({
    "uk", "gb", "britain", "british", "international", "europe", "global",
    "services", "service", "company", "co",
})


@dataclass(frozen=True)
class SponsorMatch:
    """Result of looking one employer name up against the cached register."""

    matched: bool
    matched_name: str = ""
    #: True when at least one of this sponsor's licensed routes is Skilled Worker specifically
    #: (the route that maps to what used to be called Tier 2 General) — a company can hold a
    #: sponsor licence for a different route (e.g. Intra-company Transfer) only.
    skilled_worker_route: bool = False


class SponsorRegister:
    """In-memory index over the register CSV, built once per process.

    ``_by_bucket`` narrows the fuzzy-match scan the same way ``core.job_discovery.dedup``'s own
    employer-grouping does: bucket first (the first meaningful normalised word), then run the
    more expensive subset-containment check only within the matching bucket rather than against
    every one of the ~140,000 rows.
    """

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._by_bucket: dict[str, list[tuple[str, bool]]] = {}
        for row in rows:
            name = (row.get("Organisation Name") or "").strip()
            if not name:
                continue
            bucket = company_bucket(name)
            if not bucket:
                continue
            is_skilled = _ROUTE_SKILLED_WORKER in (row.get("Route") or "").strip().casefold()
            self._by_bucket.setdefault(bucket, []).append((name, is_skilled))
        self.row_count = len(rows)

    def lookup(self, company: str) -> SponsorMatch:
        bucket = company_bucket(company)
        if not bucket:
            return SponsorMatch(matched=False)
        query_words = set(normalise_company(company).split())
        # Confirmed live against the real register: querying "Amazon" (which does have a
        # genuine, correctly-licensed "Amazon UK Services Ltd" entry) instead matched
        # "Amazon Charitable Trust" — containment (see companies_match) does not distinguish
        # "the same company written more fully" from "an unrelated legal entity that happens
        # to share a first word", and the original tie-break had no opinion between them at
        # all. Ranked ascending, so `min()` below picks: (1) a candidate whose EXTRA words
        # are all generic descriptors ("UK", "Services", ...) over one with any substantive
        # extra word — a same-entity variant is usually just the query plus a descriptor,
        # while an unrelated entity's extra words tend to be its own distinguishing name; (2)
        # among equally-generic candidates, fewer extra words; (3) the Skilled Worker route,
        # as before. Not a complete fix — a real, differently-named subsidiary can still
        # legitimately win — but it stops an obviously-unrelated org from doing so.
        def _rank(entry: tuple[str, bool]) -> tuple[bool, int, bool]:
            name, is_skilled = entry
            extra = set(normalise_company(name).split()) - query_words
            return (not extra <= _GENERIC_DESCRIPTORS, len(extra), not is_skilled)

        candidates = [
            entry
            for entry in self._by_bucket.get(bucket, [])
            if companies_match(company, entry[0])
        ]
        if not candidates:
            return SponsorMatch(matched=False)
        name, is_skilled = min(candidates, key=_rank)
        return SponsorMatch(matched=True, matched_name=name, skilled_worker_route=is_skilled)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


async def _discover_csv_url(client: httpx.AsyncClient) -> str:
    resp = await client.get(PUBLICATION_URL, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    match = _CSV_LINK_RE.search(resp.text)
    if not match:
        raise RuntimeError(
            "Could not find the sponsor register CSV link on the gov.uk publication page "
            f"({PUBLICATION_URL}) — the page layout may have changed."
        )
    return match.group(1)


def _is_stale(meta: dict) -> bool:
    try:
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
    except (KeyError, ValueError):
        return True
    return (datetime.now(UTC) - fetched_at).days >= STALE_AFTER_DAYS


async def refresh(*, force: bool = False) -> int:
    """Download the current register if the cached copy is missing or stale.

    Returns the row count of whichever copy is now on disk (freshly downloaded, or the
    still-fresh cached one). Raises on a genuine download/parse failure rather than silently
    keeping a stale file — the caller (cron or settings endpoint) decides how to report that.
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not force and _CSV_PATH.exists() and _META_PATH.exists():
        meta = json.loads(_META_PATH.read_text(encoding="utf-8"))
        if not _is_stale(meta):
            return int(meta.get("row_count", 0))

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        csv_url = await _discover_csv_url(client)
        resp = await client.get(csv_url, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        content = resp.content

    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    if len(rows) < 1000:
        # A genuine register run is ~140k rows; anything wildly smaller means the URL served
        # something other than the real file (an error page, a redirect target that changed
        # shape) — refuse to overwrite a good cached copy with garbage.
        raise RuntimeError(
            f"Downloaded sponsor register has only {len(rows)} rows — refusing to replace "
            "the cached copy with what looks like a bad download."
        )

    _CSV_PATH.write_bytes(content)
    _META_PATH.write_text(
        json.dumps({
            "fetched_at": datetime.now(UTC).isoformat(),
            "row_count": len(rows),
            "source_url": csv_url,
        }),
        encoding="utf-8",
    )
    global _register_cache
    _register_cache = None  # invalidate — the next lookup rebuilds from the new file
    logger.info("sponsor_register.refreshed", rows=len(rows), source=csv_url)
    return len(rows)


def status() -> dict:
    """Cached-file status for the settings endpoint. Never triggers a network fetch."""
    if not _META_PATH.exists():
        return {"fetched_at": None, "row_count": 0, "stale": True}
    meta = json.loads(_META_PATH.read_text(encoding="utf-8"))
    return {
        "fetched_at": meta.get("fetched_at"),
        "row_count": meta.get("row_count", 0),
        "stale": _is_stale(meta),
    }


_register_cache: SponsorRegister | None = None


def _load_index() -> SponsorRegister | None:
    global _register_cache
    if _register_cache is not None:
        return _register_cache
    if not _CSV_PATH.exists():
        return None
    _register_cache = SponsorRegister(_read_csv(_CSV_PATH))
    return _register_cache


def is_registered_sponsor(company: str) -> SponsorMatch:
    """Look ``company`` up against the cached register.

    Returns unmatched (never raises) if the register has not been downloaded yet — the
    classifier falls back to the weaker keyword signal in that case, rather than failing the
    whole ingestion pipeline for want of a reference dataset.
    """
    index = _load_index()
    if index is None:
        return SponsorMatch(matched=False)
    return index.lookup(company)
