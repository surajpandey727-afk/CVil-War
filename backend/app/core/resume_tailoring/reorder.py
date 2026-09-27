"""Put the candidate's most relevant existing evidence where it gets read first.

Reordering is the one improvement that carries no risk at all. It invents nothing, drops
nothing, changes no wording and cannot overstate a claim — it only decides which true
sentence a recruiter's eye lands on first. The brief rates it the highest-value, lowest-risk
move available, and this module makes it deterministic so it happens on every pass rather
than whenever a model remembers to suggest it.

Two constraints keep it honest. Bullets move only inside their own contiguous run, so a
bullet can never drift out from under the employer or project that introduced it. And the
sort is stable, so bullets of equal relevance stay in the order the candidate chose.
"""
# ruff: noqa: SIM905
# Word lists are written as one space-separated string and split at import. The
# suggested list literal puts sixty quoted words on a single line, which is how a
# 563-character line got into this file in the first place.


from __future__ import annotations

import re

from app.core.resume_tailoring.evidence import Coverage
from app.core.resume_tailoring.jobspec import JobSpec, Tier, equivalents
from app.core.resume_tailoring.model import LineKind, ResumeDocument, Section
from app.core.resume_tailoring.plan import BulletOrder

#: What a match is worth when ranking a bullet. A must-have counts for more than a passing
#: mention, so a bullet evidencing one mandatory requirement outranks one that happens to
#: brush three contextual ones.
_TIER_WEIGHT: dict[Tier, int] = {
    Tier.MANDATORY: 5,
    Tier.PREFERRED: 3,
    Tier.CONTEXTUAL: 1,
}

#: A run shorter than this has no meaningful ordering to improve.
_MIN_RUN = 3
#: How far ahead the best bullet must be before its run is resequenced. Relevance scoring is
#: a heuristic — one incidental mention of a required word ("business analytics team") reads
#: the same as real work on it — so a narrow win is treated as no win, and the candidate's own
#: ordering stands. Reordering should fire on the clear cases and stay out of the rest.
_MIN_MARGIN = 5


def _present(term: str, text: str) -> bool:
    return re.search(rf"(?<![\w/]){re.escape(term)}(?![\w/])", text) is not None


#: Words in the posting that carry its subject matter. Built per posting rather than from a
#: fixed list so it tracks whatever the role is actually about.
_STOP = frozenset(
    (
        "the a an and or of to in on for with by at from as is are be been being that this "
        "these those it its their our your they we you not if then than so such via across "
        "into within while during over under about through per each both all more most other "
        "new also will can who what when where which them there here have has had do does did "
        "but"
    ).split()
)


def posting_vocabulary(spec: JobSpec) -> set[str]:
    """Subject-matter words the posting uses repeatedly.

    A single passing mention is noise; a word the posting returns to is what the role is
    about. Requiring two occurrences keeps "creativity" and "passionate" out while keeping
    "data", "metadata", "platform" and "governance" in.
    """
    import re as _re
    from collections import Counter

    words = [
        w for w in _re.findall(r"[a-z][a-z-]{3,}", (spec.raw_text or "").lower())
        if w not in _STOP
    ]
    counts = Counter(words)
    return {word for word, n in counts.items() if n >= 2}


def relevance(text: str, coverage: Coverage, vocabulary: set[str] | None = None) -> int:
    """How strongly one bullet speaks to this posting.

    Only requirements the CV actually satisfies are counted. A bullet cannot earn relevance
    from a requirement nobody can evidence.
    """
    low = text.lower()
    total = 0
    for match in coverage.matches:
        if not match.satisfied:
            continue
        term = match.term.lower()
        # Check every wording that evidences the requirement, not just the one the matcher
        # happened to find first elsewhere in the CV. Scoring the literal term alone rated
        # "Built vector search and semantic retrieval across 900K+ property records" at zero
        # for a data-platform posting, and ranked a sentiment-analytics bullet above it.
        candidates = (term, *equivalents(term))
        if match.found_as:
            candidates = (*candidates, match.found_as.lower())
        if any(_present(c, low) for c in candidates if c):
            total += _TIER_WEIGHT.get(match.tier, 1)

    # A secondary, lighter signal. One requirement term can match incidentally — "business
    # analytics team" scored as highly as real analytics work and floated an internship
    # bullet to the top of a data-platform CV. Counting how much of the posting's own subject
    # vocabulary a bullet shares separates a bullet that is about the work from one that
    # merely brushes a keyword.
    if vocabulary:
        total += sum(1 for word in vocabulary if _present(word, low))
    return total


def _runs(section: Section) -> list[list[int]]:
    """Indices of each contiguous run of bullets, bounded by any non-bullet line."""
    runs: list[list[int]] = []
    current: list[int] = []
    for index, line in enumerate(section.lines):
        if line.kind is LineKind.BULLET:
            current.append(index)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def propose_reorder(
    doc: ResumeDocument, coverage: Coverage, spec: JobSpec | None = None
) -> list[BulletOrder]:
    """Rank each run of bullets by relevance, strongest first.

    Returns one entry per section that would actually change, so a pass that finds the CV
    already well ordered reports nothing rather than manufacturing a diff.
    """
    out: list[BulletOrder] = []
    vocabulary = posting_vocabulary(spec) if spec is not None else set()

    for section in doc.sections:
        ordered_ids: list[str] = []
        changed = False

        for run in _runs(section):
            lines = [section.lines[i] for i in run]
            if len(run) < _MIN_RUN:
                ordered_ids.extend(line.id for line in lines)
                continue

            scores = [relevance(line.text, coverage, vocabulary) for line in lines]
            if max(scores) - scores[0] < _MIN_MARGIN:
                # The candidate's own ordering is as good as anything this can justify.
                ordered_ids.extend(line.id for line in lines)
                continue

            ranked = sorted(
                zip(scores, range(len(lines)), lines, strict=True),
                key=lambda triple: (-triple[0], triple[1]),
            )
            new_ids = [line.id for _, _, line in ranked]
            if new_ids != [line.id for line in lines]:
                changed = True
            ordered_ids.extend(new_ids)

        if changed:
            out.append(
                BulletOrder(
                    section_heading=section.heading,
                    line_ids=ordered_ids,
                    reason=(
                        "Bullets ranked by how directly they evidence this posting's "
                        "requirements. Wording is unchanged and no bullet leaves its own "
                        "employer or project."
                    ),
                )
            )

    return out
