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
    return tuple(line.id for line in doc.all_lines() if _present(needle, line.text.lower()))


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
            coverage.matches.append(Match(req.term, req.tier, EXACT, _lines_containing(doc, term)))
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
    """A score with its working shown. Produced by the ATS evaluation engine."""

    total: int
    components: dict[str, int]
    weights: dict[str, float]
    matched: list[str]
    semantic: list[str]
    missing_mandatory: list[str]
    missing_preferred: list[str]
    #: Set when a missing critical requirement holds the score below target; shown verbatim to
    #: the operator instead of quietly inflating the number.
    constrained_by: list[str] = field(default_factory=list)
    #: The full evaluation (parsing, shortlist readiness, evidence strengths, findings).
    evaluation: object | None = field(default=None, repr=False)

    def explain(self) -> str:
        ev = self.evaluation
        if ev is not None and hasattr(ev, "explain"):
            return ev.explain()
        return f"ATS MATCH SCORE: {self.total}"


#: Requirement types that name a skill the tailoring pass can talk about (the others are
#: duties, years or credentials, which are scored but are never "keywords" to add).
_KEYWORD_TYPES = ("TECHNOLOGY", "SKILL", "DOMAIN", "TOOL", "METHODOLOGY", "BEHAVIOUR", "INDUSTRY")


def ats_score_from(evaluation) -> AtsScore:
    """Adapt an :class:`~app.core.ats_engine.Evaluation` to the tailoring pass's score shape."""
    from app.core.ats_engine.taxonomy import ReqTier, Strength

    keywords = [a for a in evaluation.assessments if a.requirement.type.value in _KEYWORD_TYPES]
    missing_critical = [
        a.requirement.term
        for a in keywords
        if a.strength is Strength.NONE and a.requirement.tier is ReqTier.CRITICAL
    ]
    return AtsScore(
        total=evaluation.ats_match,
        components=dict(evaluation.components),
        weights=dict(evaluation.weights),
        matched=[
            a.requirement.term
            for a in keywords
            if a.strength >= Strength.SUPPORTED and a.match != "semantic"
        ],
        semantic=[
            f"{a.requirement.term} (as '{a.evidence[0].text[:40]}')"
            for a in keywords
            if a.strength >= Strength.SUPPORTED and a.match == "semantic" and a.evidence
        ],
        missing_mandatory=missing_critical,
        missing_preferred=[
            a.requirement.term
            for a in keywords
            if a.strength is Strength.NONE and a.requirement.tier is not ReqTier.CRITICAL
        ],
        # The skill terms the score is held back by; duties and credentials that are also
        # missing are listed on the evaluation itself.
        constrained_by=list(missing_critical),
        evaluation=evaluation,
    )


def score(
    doc: ResumeDocument, spec: JobSpec, coverage: Coverage | None = None, *, pdf=None
) -> AtsScore:
    """Score ``doc`` against the posting with the ATS evaluation engine.

    ``coverage`` is accepted for callers that already hold one; the engine does its own,
    stronger, evidence-based matching. Pass ``pdf`` to include file-level parsing checks.
    """
    from app.core.ats_engine import evaluate

    return ats_score_from(evaluate(doc, spec.raw_text, spec.title, pdf=pdf))
