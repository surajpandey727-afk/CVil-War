"""Match a posting's requirements against what the CV actually evidences, and score it.

Two jobs, kept together because they are the same question asked twice: *what does this CV
prove?* The matcher answers it per requirement and names the line that proves it; the scorer
aggregates those answers into components an operator can argue with.

Every number here is reproducible from the same CV, posting and lexicon — no model call, no
sampling. That is a requirement, not a preference: the score is shown to the operator as
before-and-after, and a figure that drifts on its own turns the whole comparison into noise.

The scorer will not report a high number for a CV that cannot do the job. Mandatory coverage
is a separate component from overall keyword coverage precisely so that missing a must-have
shows up as a hole rather than being averaged away by a long tail of matched nice-to-haves.
"""
# ruff: noqa: SIM905
# Word lists are written as one space-separated string and split at import. The
# suggested list literal puts sixty quoted words on a single line, which is how a
# 563-character line got into this file in the first place.


from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.resume_tailoring.jobspec import (
    JobSpec,
    Tier,
    equivalents,
    implications,
    lexicon,
)
from app.core.resume_tailoring.model import ResumeDocument

#: How the components add up. Published in the result so the operator can see the arithmetic
#: rather than being handed one opaque figure.
WEIGHTS: dict[str, float] = {
    "keyword_coverage": 0.35,
    "required_skills": 0.20,
    "semantic_match": 0.15,
    "responsibility_alignment": 0.10,
    "experience_alignment": 0.10,
    "title_alignment": 0.05,
    "education": 0.05,
}


class MatchKind(str):
    """How a requirement is satisfied."""


EXACT = "exact"
SEMANTIC = "semantic"
MISSING = "missing"


@dataclass(frozen=True)
class Match:
    """One requirement, and what in the CV backs it."""

    term: str
    tier: Tier
    kind: str
    #: Ids of the lines that evidence it. Empty when missing.
    line_ids: tuple[str, ...] = ()
    #: The wording found, when it differs from the requirement's own term.
    found_as: str = ""

    @property
    def satisfied(self) -> bool:
        return self.kind != MISSING


@dataclass
class Coverage:
    """The full picture of what this CV proves against this posting."""

    matches: list[Match] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Match]:
        return [m for m in self.matches if m.kind == kind]

    def missing(self, *tiers: Tier) -> list[Match]:
        wanted = set(tiers) or set(Tier)
        return [m for m in self.matches if m.kind == MISSING and m.tier in wanted]

    def satisfied_terms(self) -> set[str]:
        return {m.term for m in self.matches if m.satisfied}


def _present(term: str, haystack: str) -> bool:
    """Whether ``term`` appears as a whole token run in ``haystack``."""
    return re.search(rf"(?<![\w/]){re.escape(term)}(?![\w/])", haystack) is not None


def _lines_containing(doc: ResumeDocument, needle: str) -> tuple[str, ...]:
    return tuple(
        line.id for line in doc.all_lines() if _present(needle, line.text.lower())
    )


def match_requirements(doc: ResumeDocument, spec: JobSpec) -> Coverage:
    """Decide, for every requirement, whether the CV evidences it and where.

    Exact wording wins; an equivalence is only consulted when the exact term is absent, and
    the wording actually found is recorded so the UI can show *why* something counted.
    """
    text = doc.to_text().lower()
    coverage = Coverage()

    for req in spec.requirements:
        term = req.term.lower()
        if _present(term, text):
            coverage.matches.append(
                Match(req.term, req.tier, EXACT, _lines_containing(doc, term))
            )
            continue

        hit = next((alt for alt in equivalents(term) if _present(alt, text)), "")
        if hit:
            coverage.matches.append(
                Match(req.term, req.tier, SEMANTIC, _lines_containing(doc, hit), found_as=hit)
            )
            continue

        coverage.matches.append(Match(req.term, req.tier, MISSING))

    return coverage


def legitimate_vocabulary(doc: ResumeDocument) -> set[str]:
    """Terms this CV may accurately be described with, whatever the posting asked for.

    Two sources: skill terms the CV states outright, and terms whose evidence the CV holds
    under other wording — a CV naming "semantic search" and "vector search" has earned the
    phrase "data discovery" even though it never uses it.

    Computed from the CV alone rather than from the posting's extracted requirements, because
    the requirement extractor only recognises phrases it has seen. A posting that writes
    "helping users discover data" never yields the token "data discovery", and an editor
    restricted to extracted requirements is then forbidden from using accurate language the
    candidate is fully entitled to.
    """
    text = doc.to_text().lower()
    earned = {term for term in lexicon() if _present(term, text)}
    for term, evidences in implications().items():
        if any(_present(alt, text) for alt in evidences):
            earned.add(term)
    return earned


@dataclass
class AtsScore:
    """A score with its working shown."""

    total: int
    components: dict[str, int]
    weights: dict[str, float]
    matched: list[str]
    semantic: list[str]
    missing_mandatory: list[str]
    missing_preferred: list[str]
    #: Set when a mandatory gap holds the score below target; shown verbatim to the operator
    #: instead of quietly inflating the number.
    constrained_by: list[str] = field(default_factory=list)

    def explain(self) -> str:
        rows = [f"ATS MATCH SCORE: {self.total}"]
        for name, value in self.components.items():
            label = name.replace("_", " ").title()
            rows.append(f"  {label:<26} {value:>3}  (w={self.weights[name]:.2f})")
        if self.constrained_by:
            rows.append(
                "  Score constrained by unsupported requirements: "
                + ", ".join(self.constrained_by)
            )
        return "\n".join(rows)


def _ratio(hit: int, total: int) -> int:
    return 100 if total == 0 else round(100 * hit / total)


def _years_claimed(doc: ResumeDocument) -> int | None:
    """The largest explicit year count the CV states about itself."""
    found = [
        int(m) for m in re.findall(r"(\d{1,2})\s*\+?\s*years?", doc.to_text(), re.I)
    ]
    return max(found) if found else None


def score(doc: ResumeDocument, spec: JobSpec, coverage: Coverage) -> AtsScore:
    """Compute the component score for this CV against this posting."""
    text = doc.to_text().lower()

    all_reqs = [
        m for m in coverage.matches if m.tier is not Tier.CONTEXTUAL
    ] or coverage.matches
    mandatory = [m for m in coverage.matches if m.tier is Tier.MANDATORY]
    semantic_pool = [m for m in coverage.matches if m.kind == SEMANTIC]

    keyword_coverage = _ratio(sum(1 for m in all_reqs if m.satisfied), len(all_reqs))
    required_skills = _ratio(sum(1 for m in mandatory if m.satisfied), len(mandatory))

    # Semantic match rewards a CV that demonstrates the requirement under its own wording.
    # Scored against everything satisfied, so a CV matching purely by exact keywords is not
    # penalised — it simply earns this component through the exact hits instead.
    satisfied = [m for m in all_reqs if m.satisfied]
    semantic_match = _ratio(len(satisfied), len(all_reqs)) if satisfied else 0
    if semantic_pool:
        semantic_match = min(100, semantic_match + 5)

    # Responsibility alignment: how many of the posting's duty lines share substantive
    # vocabulary with the CV. Stopwords stripped so "and the with" cannot carry a match.
    responsibility_alignment = _responsibility_alignment(text, spec)

    experience_alignment = _experience_alignment(doc, spec)
    title_alignment = _title_alignment(doc, spec)
    education = 100 if (not spec.degree_required or _has_degree(text)) else 0

    components = {
        "keyword_coverage": keyword_coverage,
        "required_skills": required_skills,
        "semantic_match": semantic_match,
        "responsibility_alignment": responsibility_alignment,
        "experience_alignment": experience_alignment,
        "title_alignment": title_alignment,
        "education": education,
    }
    total = round(sum(components[k] * WEIGHTS[k] for k in components))

    missing_mandatory = [m.term for m in coverage.missing(Tier.MANDATORY)]
    return AtsScore(
        total=total,
        components=components,
        weights=dict(WEIGHTS),
        matched=[m.term for m in coverage.by_kind(EXACT)],
        semantic=[f"{m.term} (as '{m.found_as}')" for m in semantic_pool],
        missing_mandatory=missing_mandatory,
        missing_preferred=[m.term for m in coverage.missing(Tier.PREFERRED)],
        constrained_by=missing_mandatory,
    )


_STOP = frozenset(
    (
        "a an and are as at be by for from has have how in into is it its of on or that the "
        "to with you your our we their they this these those will can not but if then than so "
        "such who what when where which while across about over under more most other"
    ).split()
)


def _responsibility_alignment(text: str, spec: JobSpec) -> int:
    if not spec.responsibilities:
        return 100
    hits = 0
    for duty in spec.responsibilities:
        words = {w for w in re.findall(r"[a-z][a-z/+.-]{3,}", duty.lower()) if w not in _STOP}
        if not words:
            continue
        overlap = sum(1 for w in words if w in text)
        if overlap / len(words) >= 0.30:
            hits += 1
    return _ratio(hits, len(spec.responsibilities))


def _experience_alignment(doc: ResumeDocument, spec: JobSpec) -> int:
    """How the CV's stated years compare with the posting's bar.

    A shortfall is scored down proportionally rather than zeroed: two years against a
    four-year ask is a real gap, not a disqualification, and the operator is told about it
    through ``constrained_by`` either way.
    """
    if spec.years_required is None:
        return 100
    claimed = _years_claimed(doc)
    if claimed is None:
        return 60
    if claimed >= spec.years_required:
        return 100
    return max(0, round(100 * claimed / spec.years_required))


def _title_alignment(doc: ResumeDocument, spec: JobSpec) -> int:
    """Overlap between the posting's title and the titles the CV already contains.

    Never a prompt to change a title — the CV's titles are immutable. This only measures how
    close the existing ones are, which is information the operator needs when deciding whether
    to apply at all.
    """
    if not spec.title:
        return 100
    target = {w for w in re.findall(r"[a-z]{3,}", spec.title.lower()) if w not in _STOP}
    if not target:
        return 100
    text = doc.to_text().lower()
    return _ratio(sum(1 for w in target if w in text), len(target))


def _has_degree(text: str) -> bool:
    return bool(
        re.search(r"\b(bsc|msc|ba|bs|ms|mba|phd|bachelor|master|doctor)\b", text, re.I)
    )
