"""The tailoring pass, end to end.

Reads a CV and a posting, scores the CV as it stands, asks for a short list of edits, throws
out the ones that break the rules, applies what survives, re-scores, and returns the new
document together with an account of everything that changed.

The pass fails closed. If anything structural moved — a heading, an employer line, the bullet
count, the share of original wording — the original document is returned unchanged with the
failure recorded. A CV that was not improved is a minor disappointment; a CV that quietly
stopped being the candidate's own is the defect this whole module exists to prevent.

No model is required. Without one the pass still parses, scores, reports gaps and applies the
deterministic reordering, which is useful on its own and keeps the tests independent of a
gateway being reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.core.resume_tailoring.apply import TailoringAudit, apply_plan, build_audit
from app.core.resume_tailoring.evidence import (
    AtsScore,
    Coverage,
    legitimate_vocabulary,
    match_requirements,
    score,
)
from app.core.resume_tailoring.jobspec import JobSpec, parse_job
from app.core.resume_tailoring.model import ResumeDocument
from app.core.resume_tailoring.plan import (
    DEFAULT_EDIT_BUDGET,
    SYSTEM_PROMPT,
    EditPlan,
    render_plan_prompt,
)
from app.core.resume_tailoring.reorder import propose_reorder
from app.core.resume_tailoring.validate import validate_document, validate_edits

logger = structlog.get_logger(__name__)

#: Editing a CV is a precision task, not a creative one. The account default is tuned for
#: prose and made this pass non-reproducible — the same CV and posting produced a different
#: set of edits on every run, several of them malformed. Near-zero sampling makes the plan
#: stable enough to review, and stability is what the change log is for.
PLAN_TEMPERATURE = 0.1

#: A model chosen for care rather than speed. Editing someone's CV without overstating it is
#: exactly the kind of instruction-following this is good at, and the pass runs once per
#: application rather than in a loop.
PLAN_MODEL = "openai/auto/claude-sonnet"


@dataclass
class TailoringResult:
    """Everything one pass produces."""

    original: ResumeDocument
    tailored: ResumeDocument
    audit: TailoringAudit
    before: AtsScore
    after: AtsScore
    coverage: Coverage
    spec: JobSpec

    @property
    def changed(self) -> bool:
        return self.audit.bullets_changed > 0 or bool(self.audit.reordered_sections)


async def tailor(
    doc: ResumeDocument,
    job_text: str,
    *,
    job_title: str = "",
    llm: Any | None = None,
    budget: int = DEFAULT_EDIT_BUDGET,
) -> TailoringResult:
    """Run one tailoring pass over ``doc`` for the posting in ``job_text``."""
    spec = parse_job(job_text, title=job_title)
    coverage = match_requirements(doc, spec)
    before = score(doc, spec, coverage)

    plan = EditPlan()
    if llm is not None:
        try:
            plan = await llm.complete_with_structured_output(
                prompt=render_plan_prompt(doc, spec, coverage, budget=budget),
                output_schema=EditPlan,
                system_prompt=SYSTEM_PROMPT,
                purpose="resume_tailor_minimal_diff",
                model=PLAN_MODEL,
                temperature=PLAN_TEMPERATURE,
            )
        except Exception:
            # A planning failure degrades to "no wording changes", never to a broken CV.
            logger.exception("resume_tailor_plan_failed")
            plan = EditPlan()

    # Honour the budget here as well as in the prompt; a model is free to ignore an
    # instruction, and the budget is what keeps a pass from turning into a rewrite.
    proposed = list(plan.edits)[:budget]
    # An edit may introduce a posting word the CV never used only where the matcher already
    # proved the CV evidences that requirement under other wording. Anything else has to be
    # vocabulary the CV already contains.
    vocabulary = legitimate_vocabulary(doc) | {
        match.term.lower() for match in coverage.matches if match.satisfied
    }
    allowed = frozenset(word for term in vocabulary for word in term.split())
    report = validate_edits(doc, proposed, allowed)

    # Reordering is computed here rather than asked for. It is deterministic, it cannot
    # overstate anything, and leaving it to the planner meant it simply did not happen —
    # every run returned an empty reorder list while spending its whole budget on wording.
    ordering = plan.reorder or propose_reorder(doc, coverage, spec)
    tailored = apply_plan(doc, report.accepted, ordering)
    report = validate_document(doc, tailored, report)

    if not report.ok:
        logger.warning(
            "resume_tailor_rejected", failures=report.document_failures, job=job_title,
        )
        tailored = doc.copy()

    after_coverage = match_requirements(tailored, spec)
    after = score(tailored, spec, after_coverage)

    audit = build_audit(
        original=doc,
        tailored=tailored,
        accepted=report.accepted if report.ok else [],
        rejected=report.rejected,
        before_score=before,
        after_score=after,
        reordered=[r.section_heading for r in ordering] if report.ok else [],
        document_failures=report.document_failures,
        job_title=job_title or spec.title,
    )

    logger.info(
        "resume_tailored",
        job=job_title,
        before=before.total,
        after=after.total,
        edits_accepted=len(report.accepted),
        edits_rejected=len(report.rejected),
        preserved=round(audit.preserved_ratio, 3),
    )
    return TailoringResult(
        original=doc,
        tailored=tailored,
        audit=audit,
        before=before,
        after=after,
        coverage=after_coverage,
        spec=spec,
    )
