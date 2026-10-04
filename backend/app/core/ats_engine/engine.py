"""The ATS + shortlisting evaluation engine: one résumé, one posting, an honest assessment.

Answers, with evidence, how closely this candidate's actual experience matches this actual job
and how that experience could be presented more effectively, without inventing any of it
(brief section 28). Deterministic and explainable: the same inputs give the same output, and every
figure traces to published components.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.ats_engine import report as rep
from app.core.ats_engine.matching import Assessment, assess
from app.core.ats_engine.parsing import ParsingReport, parsing_report
from app.core.ats_engine.requirements import RequirementSet, requirements_for
from app.core.ats_engine.scoring import components, headline
from app.core.ats_engine.shortlist import Shortlist, quantified_share, shortlist_readiness
from app.core.ats_engine.structure import Structure, analyse
from app.core.ats_engine.taxonomy import (
    ATS_WEIGHTS,
    SHORTLIST_WEIGHTS,
    ReqTier,
    Strength,
    band,
)
from app.core.resume_tailoring.model import ResumeDocument


@dataclass
class TierCount:
    matched: int = 0  # evidenced by real work (supported or better)
    mentioned: int = 0  # present only as a listed skill
    total: int = 0


@dataclass
class Evaluation:
    """Everything one evaluation produced."""

    ats_match: int
    parsing: int
    shortlist: int
    band: str
    shortlist_band: str
    components: dict[str, int]
    weights: dict[str, float]
    shortlist_dimensions: dict[str, int]
    shortlist_weights: dict[str, float]
    tiers: dict[str, TierCount]
    strongest: list[rep.Finding]
    weak: list[rep.Finding]
    missing: list[rep.Finding]
    unsupported: list[rep.Finding]
    problems: list[rep.Problem]
    recruiter: rep.Recruiter
    verdict: rep.Verdict
    parsing_findings: list[str] = field(default_factory=list)
    constrained_by: list[str] = field(default_factory=list)
    seniority: dict[str, object] = field(default_factory=dict)
    posting_usable: bool = True
    #: Not serialised: the raw assessments and structure, for callers that need to look closer.
    assessments: list[Assessment] = field(default_factory=list, repr=False)
    structure: Structure | None = field(default=None, repr=False)
    spec: RequirementSet | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        for key in ("assessments", "structure", "spec"):
            data.pop(key, None)
        return data

    def explain(self) -> str:
        rows = [
            f"ATS MATCH {self.ats_match}/100 ({self.band})   PARSING {self.parsing}/100   "
            f"SHORTLIST {self.shortlist}/100 ({self.shortlist_band})"
        ]
        rows += [
            f"  {k.replace('_', ' '):<26}{v:>4}  (w={self.weights[k]:.2f})"
            for k, v in self.components.items()
        ]
        if self.constrained_by:
            rows.append(
                "  Score constrained by requirements with no evidence: "
                + ", ".join(self.constrained_by)
            )
        return "\n".join(rows)


def _tiers(assessments: list[Assessment]) -> dict[str, TierCount]:
    out = {t.value: TierCount() for t in ReqTier}
    for a in assessments:
        c = out[a.requirement.tier.value]
        c.total += 1
        if a.strength >= Strength.SUPPORTED:
            c.matched += 1
        elif a.strength is Strength.MENTIONED:
            c.mentioned += 1
    return out


def evaluate(
    doc: ResumeDocument,
    job_text: str,
    job_title: str = "",
    *,
    pdf: str | Path | bytes | None = None,
    recoverable: frozenset[str] = frozenset(),
    parsing: ParsingReport | None = None,
) -> Evaluation:
    """Evaluate ``doc`` against a posting. Pass ``pdf`` to include file-level parsing checks.

    Parsing depends on the file, not the posting, so a caller scoring one résumé against many
    jobs computes it once (``parsing_report``) and passes it in.
    """
    spec = requirements_for(job_text, job_title)
    structure = analyse(doc)
    parse: ParsingReport = parsing if parsing is not None else parsing_report(doc, structure, pdf)
    assessments = assess(structure, spec) if spec.usable else []
    parts, senior, _duties = components(assessments, structure, spec, parse.score)
    ats, constrained = headline(parts, assessments)
    if not spec.usable:
        ats = 0
    short: Shortlist = shortlist_readiness(structure, assessments, spec, senior)
    quantified = quantified_share(structure)
    issues = rep.problems(assessments, structure, senior, short, parse.findings, quantified)
    missing = rep.missing(assessments)
    unsupported = [
        f
        for f in missing
        if f.requirement.lower() not in recoverable and f.tier != ReqTier.NICE.value
    ]
    return Evaluation(
        ats_match=ats,
        parsing=parse.score,
        shortlist=short.score,
        band=band(ats),
        shortlist_band=band(short.score),
        components=parts,
        weights=dict(ATS_WEIGHTS),
        shortlist_dimensions=short.dimensions,
        shortlist_weights=dict(SHORTLIST_WEIGHTS),
        tiers=_tiers(assessments),
        strongest=rep.strongest(assessments),
        weak=rep.weak(assessments, structure),
        missing=missing,
        unsupported=unsupported,
        problems=issues,
        recruiter=rep.recruiter_signal(assessments, structure, senior, quantified),
        verdict=rep.verdict(ats, short, assessments, senior, issues, recoverable),
        parsing_findings=parse.findings,
        constrained_by=constrained,
        seniority={
            "resume_level": senior.resume_level,
            "required_level": senior.required_level,
            "notes": senior.notes,
        },
        posting_usable=spec.usable,
        assessments=assessments,
        structure=structure,
        spec=spec,
    )


def simulate(
    before: Evaluation, after: Evaluation, changes: list[str] | None = None
) -> dict[str, object]:
    """Before/after comparison (brief section 20) with the lines that caused the difference."""
    rows = {
        name: {"before": before.components.get(name, 0), "after": after.components.get(name, 0)}
        for name in after.components
    }
    rows["ats_match"] = {"before": before.ats_match, "after": after.ats_match}
    rows["shortlist"] = {"before": before.shortlist, "after": after.shortlist}
    improved = [
        a.requirement.term
        for a, b in zip(before.assessments, after.assessments, strict=False)
        if b.strength > a.strength
    ]
    return {"scores": rows, "requirements_improved": improved, "caused_by": changes or []}
