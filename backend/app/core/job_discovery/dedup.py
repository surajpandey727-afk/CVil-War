"""Recognising the same job arriving from different sources.

One vacancy routinely appears on Reed, on LinkedIn, and on the employer's own board. Stored
as three rows it becomes three entries in the list, three fit analyses, and — worst — three
applications to one employer for one role, which is the most visible automation failure there
is. The ``canonical_job_id`` column has existed since the Job OS migration and nothing ever
populated it; this module is what populates it.

**Never title alone.** "Product Manager" at two different companies is two jobs; "Senior
Product Manager" and "Product Manager (Senior)" at one company on one day is one. Matching on
title alone would merge the first pair and split the second, so identity is decided by a
sequence of signals, strongest first:

1. **Same application URL** — decisive. Two adverts pointing at one form are one vacancy.
2. **Same source and source id** — the board's own identity, and the reason a re-scrape
   updates a row rather than duplicating it.
3. **Same employer + equivalent title + compatible location** — the cross-source case, and
   the only one that requires judgement.

Signals 1 and 2 are exact. Signal 3 is deliberately conservative: employer must match after
normalisation, titles must overlap strongly on their meaningful words, and locations must not
contradict each other. A false merge hides a real job the operator will never see, which is
worse than a duplicate they can ignore — so when the evidence is thin, they stay separate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import structlog

logger = structlog.get_logger(__name__)

#: Seniority markers. Extracted rather than discarded: "Staff Software Engineer" and "Senior
#: Software Engineer" are two postings, and dropping the level entirely merged them. Compared
#: separately from the role itself — see :func:`titles_match`.
_SENIORITY = {
    "senior": "senior", "snr": "senior", "sr": "senior",
    "junior": "junior", "jnr": "junior", "jr": "junior", "graduate": "junior",
    "staff": "staff",
    "principal": "principal",
    "lead": "lead",
    "head": "head", "chief": "chief", "director": "director",
    "intern": "intern", "trainee": "intern", "apprentice": "intern",
}

#: Words that carry no identity at all — grammar, contract shape, gender markers, and the
#: location fragments boards append to titles.
_TITLE_NOISE = frozenset({
    "the", "of", "and", "a", "an", "for", "to", "in", "at", "with", "or", "deputy",
    "i", "ii", "iii", "iv",
    "m", "w", "d", "f", "x",  # German "(m/w/d)" gender markers, extremely common on EU boards
    "all", "genders", "gender", "divers",
    "fulltime", "full", "time", "part", "permanent", "contract", "fte", "hybrid", "remote",
    "uk", "usa", "us", "eu", "onsite", "office",
})

#: Corporate suffixes that differ between sources for the same employer.
_COMPANY_NOISE = re.compile(
    r"\b(ltd|limited|llc|inc|incorporated|plc|gmbh|bv|nv|sa|ag|group|holdings?|"
    r"technologies|technology|labs?|software|solutions)\b",
    re.I,
)

#: Tracking parameters that make one URL look like several.
#:
#: Enumerated, never prefix-matched. A ``^gh_`` rule looked reasonable and was badly wrong:
#: it stripped ``gh_jid``, which is Greenhouse's *job id* and the only part distinguishing
#: five Wayve postings whose URLs were otherwise identical. All five collapsed into one
#: vacancy. A parameter is dropped only when it is known to be tracking.
_TRACKING = re.compile(
    r"^(utm_[a-z]+|gh_src|gclid|fbclid|ref|referrer|source|src|trk|trackingId|"
    r"lever-origin|lever-source)$",
    re.I,
)

_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")

#: Jaccard overlap the role words must reach. Jaccard, not overlap-against-the-shorter-title:
#: measuring against the shorter one meant a two-word title that was a subset of a three-word
#: title scored 1.0, which merged "Product Manager, EU" with "Product Marketing Manager" on
#: real data. Jaccard scores that pair 0.67 and rejects it.
TITLE_THRESHOLD = 0.7


def normalise_company(name: str) -> str:
    """An employer name comparable across sources.

    Boards disagree about suffixes constantly: "Ocado" on one, "Ocado Group" on another,
    "Monzo Bank Ltd" on a third.
    """
    text = _NON_WORD.sub(" ", (name or "").casefold())
    text = _COMPANY_NOISE.sub(" ", text)
    return _WS.sub(" ", text).strip()


def companies_match(left: str, right: str) -> bool:
    """True when two employer names denote the same company.

    Equality after normalisation is not enough. Boards write "Monzo", "Monzo Bank" and
    "Monzo Bank Ltd" for one employer, and no stopword list survives that indefinitely —
    stripping "bank" would then have to strip "group", "labs", "studios", and so on for ever,
    each removal risking a real distinction.

    So the rule is containment: one name's words being a subset of the other's means the same
    employer described at different lengths. It is a deliberate, bounded risk — "Apple" would
    match "Apple Bank" — which is acceptable only because company agreement alone never
    merges anything. Signal 3 additionally requires an equivalent title and a compatible
    location, and two genuinely different employers advertising the same role in the same
    city is rare enough to accept against the alternative of splitting every employer whose
    name a board wrote slightly differently.
    """
    a = set(normalise_company(left).split())
    b = set(normalise_company(right).split())
    if not a or not b:
        return False
    return a <= b or b <= a


def company_bucket(name: str) -> str:
    """A stable grouping key, unaffected by suffix variation.

    The first meaningful word: "monzo" for all of Monzo / Monzo Bank / Monzo Bank Ltd, so
    every spelling lands in one bucket and the pairwise check sees them.
    """
    words = normalise_company(name).split()
    return words[0] if words else ""


def title_seniority(title: str) -> str:
    """The seniority a title declares, or empty."""
    for word in _NON_WORD.sub(" ", (title or "").casefold()).split():
        level = _SENIORITY.get(word)
        if level:
            return level
    return ""


def title_tokens(title: str) -> frozenset[str]:
    """The role-identifying words of a title, with seniority and filler removed."""
    words = _NON_WORD.sub(" ", (title or "").casefold()).split()
    return frozenset(
        w for w in words
        if w and w not in _TITLE_NOISE and w not in _SENIORITY and len(w) > 1
    )


def titles_match(
    left: str,
    right: str,
    *,
    threshold: float = TITLE_THRESHOLD,
    ignore: frozenset[str] = frozenset(),
) -> bool:
    """True when two titles plausibly name the same role at the same level.

    Two independent checks, because real data broke each of them separately:

    * **Role words, by Jaccard.** Measuring overlap against the shorter title scored a subset
      as a perfect match, which merged "Senior Product Manager, EU" with "Senior Product
      Marketing Manager" — the extra word in the longer title carried the whole distinction.
      Jaccard counts that extra word against the match.
    * **Seniority must agree.** "Staff Software Engineer" and "Senior Software Engineer" have
      identical role words. They are two postings, and treating a level difference as noise
      merged them. Equal, or absent on both sides; anything else is a different posting.

    ``ignore`` removes words the caller knows carry no role meaning here — in practice the
    place names taken from the listings' own location fields, because boards append
    "- London - Hybrid" to titles and no hard-coded city list would keep up.
    """
    a, b = title_tokens(left) - ignore, title_tokens(right) - ignore
    if not a or not b:
        return False
    if title_seniority(left) != title_seniority(right):
        return False
    return len(a & b) / len(a | b) >= threshold


def canonical_url(url: str) -> str:
    """A URL stripped of the things that vary without changing the destination.

    Scheme, host case, tracking parameters and trailing slashes all differ between sources
    linking to one form. Query parameters that are *not* tracking are kept, because plenty of
    ATS URLs carry the job id there.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw if "//" in raw else f"https://{raw}")
    except ValueError:
        return raw.casefold()

    host = (parts.hostname or "").casefold().removeprefix("www.")
    path = parts.path.rstrip("/")
    kept = [
        pair for pair in parts.query.split("&")
        if pair and not _TRACKING.match(pair.split("=", 1)[0])
    ]
    return urlunsplit(("https", host, path, "&".join(sorted(kept)), ""))


def locations_compatible(left: str, right: str) -> bool:
    """True unless two locations positively contradict each other.

    Deliberately permissive. One source says "London", another says "London, UK", a third
    says nothing at all — none of those is evidence of a different job. Only two specific,
    non-overlapping places count as a contradiction, and a blank never does.
    """
    a = _WS.sub(" ", _NON_WORD.sub(" ", (left or "").casefold())).strip()
    b = _WS.sub(" ", _NON_WORD.sub(" ", (right or "").casefold())).strip()
    if not a or not b:
        return True
    if a == b:
        return True
    a_words, b_words = set(a.split()), set(b.split())
    return bool(a_words & b_words)


@dataclass(frozen=True)
class JobIdentity:
    """The comparable identity of one job listing."""

    source: str
    source_id: str
    company: str
    title: str
    location: str
    url: str
    application_url: str = ""

    @property
    def company_key(self) -> str:
        """Grouping key. Comparison uses :func:`companies_match`, not this."""
        return company_bucket(self.company)

    @property
    def apply_key(self) -> str:
        """The strongest signal: where the application actually happens."""
        return canonical_url(self.application_url or "")

    @property
    def url_key(self) -> str:
        return canonical_url(self.url or "")


def same_job(left: JobIdentity, right: JobIdentity) -> bool:
    """Do these two listings describe one vacancy?

    Checked strongest signal first so the expensive comparison only runs when the cheap ones
    are inconclusive.
    """
    # 1. Same application form. Decisive regardless of how the adverts are worded.
    if left.apply_key and left.apply_key == right.apply_key:
        return True

    # 2. Same board, same id — a re-scrape of the same posting.
    if (
        left.source
        and left.source == right.source
        and left.source_id
        and left.source_id == right.source_id
    ):
        return True

    # 2b. Same canonical advert URL across sources (an aggregator linking to the ATS).
    if left.url_key and left.url_key == right.url_key:
        return True

    # 3. The cross-source case, and the only one requiring judgement.
    #
    # Restricted to *different* sources on purpose. When one board publishes two postings
    # under two of its own ids, the board is asserting they are different jobs, and it knows
    # better than any title heuristic. Ignoring that merged three unrelated arbeitnow
    # engineering roles into one on real data.
    if left.source and left.source == right.source:
        return False
    if not companies_match(left.company, right.company):
        return False
    # Place names come from the listings themselves rather than a city list: a board that
    # appends its location to the title is describing the same role, and the location column
    # already tells us which words those are.
    place_words = frozenset(
        word
        for location in (left.location, right.location)
        for word in _NON_WORD.sub(" ", (location or "").casefold()).split()
        if len(word) > 1
    )
    if not titles_match(left.title, right.title, ignore=place_words):
        return False
    return locations_compatible(left.location, right.location)


def group(identities: list[JobIdentity]) -> list[list[int]]:
    """Cluster listings that describe the same vacancy, returning index groups.

    Union-find over pairwise matches, so A~B and B~C puts all three together even where A and
    C would not have matched directly — one source's wording often bridges two others.
    """
    parent = list(range(len(identities)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    # Employer buckets first: two listings from different companies can never merge under
    # signal 3, and the URL signals are exact, so this avoids an O(n^2) sweep over the lot.
    by_company: dict[str, list[int]] = {}
    for index, identity in enumerate(identities):
        by_company.setdefault(identity.company_key, []).append(index)

    by_apply: dict[str, int] = {}
    by_url: dict[str, int] = {}
    for index, identity in enumerate(identities):
        for key, table in ((identity.apply_key, by_apply), (identity.url_key, by_url)):
            if not key:
                continue
            if key in table:
                union(table[key], index)
            else:
                table[key] = index

    for indexes in by_company.values():
        for position, left in enumerate(indexes):
            for right in indexes[position + 1:]:
                if same_job(identities[left], identities[right]):
                    union(left, right)

    clusters: dict[int, list[int]] = {}
    for index in range(len(identities)):
        clusters.setdefault(find(index), []).append(index)
    return list(clusters.values())
