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

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.exceptions import GenerationError
from app.core.llm.prompts.standing import (
    ATS_EVALUATION_STANDARD,
    RESUME_GENERATION_STANDARD,
    with_standing,
)
from app.core.resume_tailoring.apply import TailoringAudit, apply_plan, build_audit
from app.core.resume_tailoring.declared import with_declared
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
from app.core.resume_tailoring.trusted import TrustedSource, evidence_text, sources_containing
from app.core.resume_tailoring.validate import (
    _numbers,
    _tokens,
    validate_document,
    validate_edits,
)

logger = structlog.get_logger(__name__)

#: How long one planning call may take before the model is treated as unavailable.
PLAN_TIMEOUT_SECONDS = 90


class PlanningFailed(GenerationError):  # noqa: N818 (a condition the caller handles, not a bug)
    """The language model could not be used for this pass (down, timed out, or unusable output)."""

#: Editing a CV is a precision task, not a creative one. The account default is tuned for
#: prose and made this pass non-reproducible — the same CV and posting produced a different
#: set of edits on every run, several of them malformed. Near-zero sampling makes the plan
#: stable enough to review, and stability is what the change log is for.
PLAN_TEMPERATURE = 0.1

#: A model chosen for care rather than speed. Editing someone's CV without overstating it is
#: exactly the kind of instruction-following this is good at, and the pass runs once per
#: application rather than in a loop.
#: Rejections a second attempt cannot repair: the edit was a repeat, or targeted nothing.
_NOT_WORTH_RETRY = frozenset({"no_op", "duplicate", "unknown_line", "empty"})

PLAN_MODEL = "openai/auto/claude-sonnet"


def recovered_facts(
    doc: ResumeDocument, accepted: list, trusted: Sequence[TrustedSource]
) -> dict[str, tuple[list[str], list[str]]]:
    """For each accepted edit, the words/figures it took from trusted evidence, and from where.

    A term counts as recovered when the edit uses it, the current résumé does not contain it,
    and a trusted source does. Everything else the edit wrote is already in the résumé.
    """
    if not trusted:
        return {}
    cv_tokens = _tokens(doc.to_text())
    cv_numbers = _numbers(doc.to_text())
    out: dict[str, tuple[list[str], list[str]]] = {}
    for edit in accepted:
        line = doc.bullet_by_id(edit.line_id)
        if line is None:
            continue
        words = {
            w for w in _tokens(edit.after_text) - _tokens(line.text) if w not in cv_tokens and len(w) > 2
        }
        figures = _numbers(edit.after_text) - _numbers(line.text) - cv_numbers
        terms = sorted(words | figures)
        sources = sources_containing(terms, trusted)
        if terms and sources:
            out[edit.line_id] = (terms, sources)
    return out


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
    #: line id -> (terms recovered from trusted evidence, source labels), accepted edits only.
    recovery: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)

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
    allow_reorder: bool = True,
    trusted: Sequence[TrustedSource] = (),
    exclude: frozenset[str] = frozenset(),
    focus: Sequence[str] = (),
) -> TailoringResult:
    """Run one tailoring pass over ``doc`` for the posting in ``job_text``.

    ``allow_reorder`` is switched off for a PDF edited in place: moving a bullet changes where
    every line below it sits, which is the layout change an in-place edit exists to avoid.
    """
    spec = parse_job(job_text, title=job_title)
    # The owner's declared experience is evidence on every pass (see ``declared``): a term the CV
    # omits is recoverable from it, and the change log cites it.
    trusted = with_declared(tuple(trusted), job_text, job_title)
    coverage = match_requirements(doc, spec)
    before = score(doc, spec, coverage)

    plan = EditPlan()
    base_prompt = render_plan_prompt(
        doc, spec, coverage, budget=budget, trusted=tuple(trusted), exclude=exclude, focus=tuple(focus)
    )
    system = with_standing(SYSTEM_PROMPT, RESUME_GENERATION_STANDARD, ATS_EVALUATION_STANDARD)

    async def ask(prompt: str) -> EditPlan:
        try:
            return await asyncio.wait_for(
                llm.complete_with_structured_output(
                    prompt=prompt,
                    output_schema=EditPlan,
                    system_prompt=system,
                    purpose="resume_tailor_minimal_diff",
                    model=PLAN_MODEL,
                    temperature=PLAN_TEMPERATURE,
                ),
                timeout=PLAN_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            # Never a broken or silently unchanged CV: the caller is told the model could not be
            # used, so the person can retry instead of being told "nothing more to improve".
            logger.exception("resume_tailor_plan_failed")
            raise PlanningFailed(
                "The language model did not give a usable answer"
                + (" in time" if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) else "")
                + ", so no résumé was generated. Nothing was saved; please try again."
            ) from exc

    if llm is not None:
        plan = await ask(base_prompt)

    # Honour the budget here as well as in the prompt; a model is free to ignore an
    # instruction, and the budget is what keeps a pass from turning into a rewrite.
    proposed = [e for e in plan.edits if e.line_id not in exclude][:budget]
    # An edit may introduce a posting word the CV never used only where the matcher already
    # proved the CV evidences that requirement under other wording. Anything else has to be
    # vocabulary the CV already contains.
    vocabulary = legitimate_vocabulary(doc) | {
        match.term.lower() for match in coverage.matches if match.satisfied
    }
    allowed = frozenset(word for term in vocabulary for word in term.split())
    evidence = evidence_text(trusted)
    report = validate_edits(doc, proposed, allowed, evidence)

    # One corrective pass. The first plan often reaches for the posting's own words (which the CV
    # cannot support) or echoes a line back. Rather than ship nothing, say exactly what failed and
    # ask once more for edits built only from wording the CV or trusted evidence already has.
    retry_worthy = [r for r in report.rejected if r.rule not in _NOT_WORTH_RETRY]
    if llm is not None and retry_worthy and len(report.accepted) < budget:
        taken = {e.line_id for e in report.accepted}
        feedback = "\n".join(f"- {r.line_id}: {r.rule} — {r.detail}" for r in retry_worthy)
        review = (
            base_prompt
            + "\n\nREVIEW OF YOUR PREVIOUS ATTEMPT. These edits were rejected by the validators, "
            "so they cannot be used as written:\n" + feedback
            + "\n\nPropose corrected edits only where the improvement can be made using wording "
            "that already appears in the CV or in the trusted evidence, and keep every figure and "
            "technology exactly as the source states it. If a line cannot be improved that way, "
            "leave it out. Do not repeat a rejected edit, and do not return a line unchanged."
        )
        try:
            second = await ask(review)
        except PlanningFailed:
            second = EditPlan()  # the first plan already stands; a failed second opinion adds nothing
        retry_edits = [e for e in second.edits if e.line_id not in taken and e.line_id not in exclude][
            : budget - len(report.accepted)
        ]
        retry_report = validate_edits(doc, retry_edits, allowed, evidence)
        seen_rejections = {(r.line_id, r.rule) for r in report.rejected}
        report.accepted.extend(retry_report.accepted)
        report.rejected.extend(
            r for r in retry_report.rejected if (r.line_id, r.rule) not in seen_rejections
        )
        # Whatever the retry fixed is no longer a failure to report.
        fixed = {e.line_id for e in retry_report.accepted}
        report.rejected = [r for r in report.rejected if r.line_id not in fixed]
        proposed = proposed + retry_edits
        plan.reorder = plan.reorder or second.reorder

    # Reordering is computed here rather than asked for. It is deterministic, it cannot
    # overstate anything, and leaving it to the planner meant it simply did not happen —
    # every run returned an empty reorder list while spending its whole budget on wording.
    ordering = (plan.reorder or propose_reorder(doc, coverage, spec)) if allow_reorder else []
    tailored = apply_plan(doc, report.accepted, ordering)
    report = validate_document(doc, tailored, report)

    if not report.ok:
        logger.warning(
            "resume_tailor_rejected", failures=report.document_failures, job=job_title,
        )
        tailored = doc.copy()

    after_coverage = match_requirements(tailored, spec)
    after = score(tailored, spec, after_coverage)

    recovery = recovered_facts(doc, report.accepted if report.ok else [], trusted)
    audit = build_audit(
        original=doc,
        tailored=tailored,
        accepted=report.accepted if report.ok else [],
        recovery=recovery,
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
        recovery=recovery,
    )
