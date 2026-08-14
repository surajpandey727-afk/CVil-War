"""Job-vs-CV fit analysis: what matches, what does not, and what to do about it.

The existing ATS scorer answers "how well does this CV score" with five numbers. That is not
enough to decide whether to apply. This module answers the questions an operator actually
asks: which requirements do I meet, where in my CV is the proof, what am I missing, and what
should I change — without ever telling them they have experience they do not.

**Structure: deterministic skeleton, LLM for language.**

Requirement extraction and evidence matching are language problems, so an LLM does them when
one is configured. Everything else is arithmetic done here: category scores are computed from
the match levels, not asked for, because a model asked to produce a percentage will produce a
confident one whether or not it has grounds. The model's job is to find and quote; the scoring
is ours.

When no LLM is available the analysis still runs — :func:`keyword_requirements` extracts
requirements from the posting with the existing skill vocabulary and the matcher does literal
lookups. The result declares ``method="keyword"`` so a degraded analysis is never mistaken for
a full one.

**The anti-fabrication guards, which are the point of the module:**

1. Every match must quote CV text that is actually present. :func:`_verify_evidence` drops any
   match whose quoted evidence does not appear in the CV — a model that paraphrases loses the
   match rather than having its paraphrase presented as a quotation.
2. A category is scored only when the posting supplies something to score against. No salary
   in the advert means no salary score, stated as such.
3. Recommendations are grounded in existing CV material, or explicitly typed
   ``cannot_evidence``. There is no path that emits "add your 5 years of AWS" for someone with
   no AWS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from app.schemas.fit import (
    EvidenceSource,
    FitCategory,
    MatchLevel,
    Recommendation,
    RequirementMatch,
)

logger = structlog.get_logger(__name__)

#: Weight of each match level when averaging into a category score. STRONG is not 1.0:
#: "clearly evidenced" and "outstanding, quantified evidence" are different, and flattening
#: them removes the CV's only signal that something is a genuine strength.
LEVEL_WEIGHT: dict[MatchLevel, float] = {
    MatchLevel.EXCELLENT: 1.0,
    MatchLevel.STRONG: 0.85,
    MatchLevel.PARTIAL: 0.5,
    MatchLevel.WEAK: 0.25,
    MatchLevel.MISSING: 0.0,
}

#: A required gap costs more than a preferred one. Applied when averaging, so a CV that meets
#: every must-have and misses two nice-to-haves does not score the same as the reverse.
REQUIRED_WEIGHT = 2.0
PREFERRED_WEIGHT = 1.0

#: Section headers used to attribute a quote back to part of the CV. Deliberately broad: a
#: wrong attribution is worse than none, so anything unmatched stays UNATTRIBUTED.
_SECTION_PATTERNS: tuple[tuple[EvidenceSource, re.Pattern[str]], ...] = (
    (
        EvidenceSource.EXPERIENCE,
        re.compile(
            r"^\s*(work\s+)?(experience|employment|career|professional\s+experience|history)\b",
            re.I | re.M,
        ),
    ),
    (
        EvidenceSource.EDUCATION,
        re.compile(r"^\s*(education|academic|qualifications)\b", re.I | re.M),
    ),
    (
        EvidenceSource.SKILLS,
        re.compile(r"^\s*(skills|technical\s+skills|competencies)\b", re.I | re.M),
    ),
    (
        EvidenceSource.CERTIFICATIONS,
        re.compile(r"^\s*(certifications?|licen[cs]es?)\b", re.I | re.M),
    ),
    (EvidenceSource.PROJECTS, re.compile(r"^\s*(projects?|portfolio)\b", re.I | re.M)),
    (EvidenceSource.SUMMARY, re.compile(r"^\s*(summary|profile|objective|about)\b", re.I | re.M)),
)

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Whitespace- and case-insensitive form, for containment checks."""
    return _WS.sub(" ", (text or "").casefold()).strip()


@dataclass(frozen=True)
class CvIndex:
    """A CV prepared for evidence lookups.

    Sections are located once so every match can be attributed without re-scanning, and the
    normalised full text is kept for the containment check that verifies quotations.
    """

    text: str
    normalised: str
    #: ``(source, start, end)`` character spans, in document order.
    sections: tuple[tuple[EvidenceSource, int, int], ...]

    def section_at(self, index: int) -> EvidenceSource:
        for source, start, end in self.sections:
            if start <= index < end:
                return source
        return EvidenceSource.UNATTRIBUTED

    def locate(self, quote: str) -> int:
        """Character offset of ``quote`` in the CV, or -1 if it is not there."""
        target = normalise(quote)
        if not target:
            return -1
        position = self.normalised.find(target)
        if position < 0:
            return -1
        # The normalised string collapses whitespace, so the index is approximate. Good
        # enough for section attribution, which only needs the right region.
        return int(position * (len(self.text) / max(len(self.normalised), 1)))


def build_index(cv_text: str) -> CvIndex:
    """Locate the CV's sections so evidence can be attributed to one."""
    spans: list[tuple[EvidenceSource, int, int]] = []
    hits: list[tuple[int, EvidenceSource]] = []
    for source, pattern in _SECTION_PATTERNS:
        for match in pattern.finditer(cv_text or ""):
            hits.append((match.start(), source))
    hits.sort()
    for position, (start, source) in enumerate(hits):
        end = hits[position + 1][0] if position + 1 < len(hits) else len(cv_text or "")
        spans.append((source, start, end))
    return CvIndex(text=cv_text or "", normalised=normalise(cv_text), sections=tuple(spans))


#: Employer/institution line, used to answer "CV → Experience → SimplyPhi". Matched near the
#: evidence rather than guessed from the whole CV.
#: The dashes are given as escapes because they are indistinguishable from a hyphen in a
#: monospaced diff, and this pattern is easy to break by "tidying" one into the other.
_EMPLOYER = re.compile("^\\s*([A-Z][\\w&.,'\\- ]{2,60}?)\\s*(?:[|\\u2013\\u2014-]|,)\\s", re.M)


def attribute(index: CvIndex, quote: str) -> tuple[EvidenceSource | None, str]:
    """Where in the CV a quote sits, and under which employer if that is determinable.

    Returns ``(None, "")`` when the quote is not in the CV at all — the caller treats that as
    a failed verification, not as an unattributed match.
    """
    position = index.locate(quote)
    if position < 0:
        return None, ""
    source = index.section_at(position)
    # Look backwards a short way for the nearest employer-looking line, so the attribution
    # belongs to this entry rather than to whichever employer appears first in the CV.
    window = index.text[max(0, position - 600) : position]
    employers = _EMPLOYER.findall(window)
    return source, (employers[-1].strip() if employers else "")


def verify_matches(
    index: CvIndex, matches: list[RequirementMatch]
) -> tuple[list[RequirementMatch], int]:
    """Keep only matches whose evidence genuinely appears in the CV.

    This is the guard that makes the whole report trustworthy. A model asked for evidence will
    sometimes produce a fluent paraphrase; presenting that as a quotation would be inventing
    the operator's CV back at them. A quote that cannot be found downgrades the match to
    MISSING with its evidence stripped, rather than being silently dropped — the requirement
    still belongs in the report.

    Returns the verified list and the number of claims that failed verification.
    """
    verified: list[RequirementMatch] = []
    rejected = 0
    for match in matches:
        if match.level is MatchLevel.MISSING:
            verified.append(match.model_copy(update={"evidence": "", "source": None}))
            continue
        source, detail = attribute(index, match.evidence)
        if source is None:
            rejected += 1
            logger.info(
                "fit.evidence_unverified",
                requirement=match.requirement[:80],
                quoted=match.evidence[:80],
            )
            verified.append(
                match.model_copy(
                    update={
                        "level": MatchLevel.MISSING,
                        "evidence": "",
                        "source": None,
                        "source_detail": "",
                    }
                )
            )
            continue
        verified.append(
            match.model_copy(
                update={
                    "source": source,
                    "source_detail": detail or match.source_detail,
                }
            )
        )
    return verified, rejected


def score_categories(
    matches: list[RequirementMatch], *, job_facts: dict[str, object]
) -> tuple[list[FitCategory], list[str]]:
    """Turn verified matches and known job facts into scored categories.

    Computed here rather than asked of a model, because a model asked for a percentage
    returns a confident one regardless of grounds. Each category also reports its ``method``,
    so the UI can answer "where did this number come from".

    A dimension the posting says nothing about is not scored at all; it is returned in the
    second element with the reason, and the UI states it.
    """
    categories: list[FitCategory] = []
    not_assessed: list[str] = []

    required = [m for m in matches if m.required is True]
    preferred = [m for m in matches if m.required is False]
    unclassified = [m for m in matches if m.required is None]

    def weighted(group: list[RequirementMatch], weight: float) -> tuple[float, float]:
        return (
            sum(LEVEL_WEIGHT[m.level] * weight for m in group),
            len(group) * weight,
        )

    if required:
        got, total = weighted(required, REQUIRED_WEIGHT)
        categories.append(
            FitCategory(
                key="required_skills",
                label="Required skills",
                score=got / total,
                rationale=(
                    f"{sum(1 for m in required if LEVEL_WEIGHT[m.level] >= 0.85)} of "
                    f"{len(required)} required items clearly evidenced."
                ),
                method="Average of match levels; required items weighted double.",
            )
        )
    else:
        not_assessed.append("Required skills — the posting does not separate must-haves.")

    if preferred:
        got, total = weighted(preferred, PREFERRED_WEIGHT)
        categories.append(
            FitCategory(
                key="preferred_skills",
                label="Preferred skills",
                score=got / total,
                rationale=f"{sum(1 for m in preferred if LEVEL_WEIGHT[m.level] >= 0.85)} of "
                f"{len(preferred)} preferred items evidenced.",
                method="Average of per-requirement match levels.",
            )
        )
    else:
        not_assessed.append("Preferred skills — the posting lists none separately.")

    if unclassified and not required:
        got, total = weighted(unclassified, PREFERRED_WEIGHT)
        categories.append(
            FitCategory(
                key="requirements",
                label="Requirements",
                score=got / total,
                rationale=f"{len(unclassified)} requirements assessed; the posting does not mark "
                "any as required or preferred.",
                method="Average of per-requirement match levels.",
            )
        )

    seniority = job_facts.get("seniority")
    cv_seniority = job_facts.get("cv_seniority")
    if seniority and cv_seniority:
        score = 1.0 if str(seniority).casefold() == str(cv_seniority).casefold() else 0.6
        categories.append(
            FitCategory(
                key="seniority",
                label="Seniority",
                score=score,
                rationale=f"Posting reads as {seniority}; your CV reads as {cv_seniority}.",
                method="Seniority terms detected in the posting title and your CV.",
            )
        )
    elif not seniority:
        not_assessed.append("Seniority — the posting does not state a level.")

    location_fit = job_facts.get("location_fit")
    if location_fit is not None:
        categories.append(
            FitCategory(
                key="location",
                label="Location",
                score=float(location_fit),  # type: ignore[arg-type]
                rationale=str(job_facts.get("location_reason") or ""),
                method="Posting location compared with your target location.",
            )
        )
    else:
        not_assessed.append("Location — the posting gives no location.")

    if job_facts.get("salary_min_k") or job_facts.get("salary_max_k"):
        expectation = job_facts.get("salary_expectation_k")
        if expectation:
            top = float(job_facts.get("salary_max_k") or job_facts.get("salary_min_k") or 0)
            score = 1.0 if top >= float(expectation) else max(0.0, top / float(expectation))
            categories.append(
                FitCategory(
                    key="salary",
                    label="Salary",
                    score=score,
                    rationale=f"Posting pays up to £{int(top)}k; you are targeting "
                    f"£{int(float(expectation))}k.",
                    method="Published band compared with your stated minimum.",
                )
            )
        else:
            not_assessed.append(
                "Salary — the posting publishes a band but you have set no expectation."
            )
    else:
        # The common case for UK postings, and the one where a fabricated score would be
        # most convincing.
        not_assessed.append("Salary — the posting publishes no band.")

    if job_facts.get("industry"):
        not_assessed.append(
            f"Industry — the posting is in {job_facts['industry']}, but your CV does not "
            "state an industry to compare it with."
        ) if not job_facts.get("cv_industry") else categories.append(
            FitCategory(
                key="industry",
                label="Industry",
                score=(
                    1.0
                    if normalise(str(job_facts["industry"]))
                    == normalise(str(job_facts["cv_industry"]))
                    else 0.5
                ),
                rationale=f"Posting industry: {job_facts['industry']}.",
                method="Posting industry compared with the industry detected in your CV.",
            )
        )

    return categories, not_assessed


#: How much each category counts toward the headline number.
#:
#: Not a flat average, and the difference is load-bearing. Weighting required items inside
#: ``required_skills`` achieves nothing if the categories are then averaged evenly: a CV that
#: meets every must-have and misses the nice-to-haves scored *identically* to one that missed
#: every must-have and met the nice-to-haves. Must-haves are what get a CV rejected, so they
#: dominate here too.
CATEGORY_WEIGHT: dict[str, float] = {
    "required_skills": 3.0,
    "requirements": 3.0,
    "preferred_skills": 1.0,
    "seniority": 1.5,
    "industry": 1.0,
    "location": 1.0,
    "salary": 1.0,
}
_DEFAULT_CATEGORY_WEIGHT = 1.0


def overall_score(categories: list[FitCategory]) -> float:
    """The headline number: a weighted mean of what was actually assessed.

    Unassessed dimensions are excluded rather than counted as zero or as a neutral 0.5 —
    either would let the absence of information move a score that is supposed to reflect
    evidence.
    """
    if not categories:
        return 0.0
    weights = [CATEGORY_WEIGHT.get(c.key, _DEFAULT_CATEGORY_WEIGHT) for c in categories]
    total = sum(weights)
    if total <= 0:
        return 0.0
    return round(
        sum(c.score * w for c, w in zip(categories, weights, strict=True)) / total, 4
    )


def build_recommendations(matches: list[RequirementMatch]) -> list[Recommendation]:
    """Turn gaps into advice the operator can act on honestly.

    The ordering is deliberate: things they can evidence but have not, first; things they
    genuinely cannot claim, last and labelled as such. A recommendation never says "add X"
    for an X the CV contains no trace of — that one becomes "cannot evidence", which is the
    honest advice and also the useful one, because it tells them where the real gap is.
    """
    out: list[Recommendation] = []
    for match in matches:
        if match.level in (MatchLevel.PARTIAL, MatchLevel.WEAK) and match.evidence:
            out.append(
                Recommendation(
                    text=f"Strengthen the evidence for {match.requirement}. Your CV mentions it "
                    f"(“{match.evidence[:110]}”) but not prominently — make the "
                    "ownership and the outcome explicit.",
                    kind="strengthen",
                    requirement=match.requirement,
                    grounded_in=match.evidence[:200],
                )
            )
        elif match.level is MatchLevel.MISSING:
            out.append(
                Recommendation(
                    text=f"{match.requirement}: not evidenced in your CV. If you have done this, "
                    "add it with a concrete example; if not, this is a genuine gap for this "
                    "role.",
                    kind="cannot_evidence",
                    requirement=match.requirement,
                )
            )
    # Quantification advice, but only where there is something to quantify.
    for match in matches:
        quantifiable = (
            match.level in (MatchLevel.STRONG, MatchLevel.EXCELLENT)
            and match.evidence
            and not re.search(r"\d", match.evidence)
        )
        if quantifiable:
            out.append(
                Recommendation(
                    text=f"Quantify {match.requirement}. The evidence is there but carries no "
                    "numbers — scale, budget or measured outcome would make it land.",
                    kind="quantify",
                    requirement=match.requirement,
                    grounded_in=match.evidence[:200],
                )
            )
    return out[:12]
