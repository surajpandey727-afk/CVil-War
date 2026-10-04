"""Tailor a CV that is a PDF, and hand back the same PDF with only the right words changed.

Order of work, and why each step is where it is:

1. Read the PDF with its layout, so every editable paragraph knows where it sits.
2. Run the ordinary tailoring pass (plan -> validate). Reordering is off: moving a bullet moves
   everything beneath it, which is the layout change this whole path exists to prevent.
3. Write the surviving edits into a copy of the PDF. Any edit that cannot be placed without
   disturbing the page is dropped and recorded, never forced.
4. Check the file itself (see ``pdf_check``). If the set as a whole fails, edits are re-applied
   one at a time and only those that pass are kept.
5. Read the finished PDF back and score *that*. The number the candidate sees is the number for
   the file they will submit, not for an intermediate string in memory.
6. If the score is below the target, run further rounds that work only on lines not yet edited
   and only on requirements the résumé already evidences weakly. A round that does not raise the
   score is thrown away, and a final file that scores below the original is never shipped.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from app.core.exceptions import GenerationError
from app.core.resume_tailoring.apply import TailoringAudit, build_audit
from app.core.resume_tailoring.declared import excluded_terms_added, with_declared
from app.core.resume_tailoring.engine import PlanningFailed, tailor
from app.core.resume_tailoring.evidence import AtsScore, score
from app.core.resume_tailoring.jobspec import parse_job
from app.core.resume_tailoring.model import ResumeDocument
from app.core.resume_tailoring.pdf_check import PdfCheck, check_edited_pdf
from app.core.resume_tailoring.pdf_edit import PdfEditResult, edit_pdf_in_place
from app.core.resume_tailoring.pdf_fit import fit_pagination
from app.core.resume_tailoring.pdf_layout import build_document
from app.core.resume_tailoring.plan import BANNED_PHRASES, ProposedEdit
from app.core.resume_tailoring.trusted import TrustedSource
from app.core.resume_tailoring.validate import Rejection, _numbers

logger = structlog.get_logger(__name__)

#: The ATS match the loop works toward. A target, never a promise: a round must earn its points
#: from evidence the résumé has, and the loop stops when it cannot.
ATS_TARGET = 82
MAX_ROUNDS = 5


@dataclass
class PdfTailoring:
    """Everything one PDF tailoring pass produced, for the caller to store and report."""

    status: str  # "generated" | "unchanged"
    path: Path
    original: ResumeDocument
    expected: ResumeDocument
    final: ResumeDocument
    audit: TailoringAudit
    before: AtsScore
    after: AtsScore
    edit: PdfEditResult
    check: PdfCheck
    details: dict[str, Any] = field(default_factory=dict)


def _expected_document(original: ResumeDocument, edits: dict[str, str]) -> ResumeDocument:
    doc = original.copy()
    for line in doc.all_lines():
        if line.id in edits:
            line.text = edits[line.id].strip()
    return doc


def _place(
    src: Path, original: ResumeDocument, proposed: dict[str, str], out: Path
) -> tuple[dict[str, str], PdfEditResult, PdfCheck, list[Rejection]]:
    """Apply as many of ``proposed`` as the page and the checks allow."""
    rejections: list[Rejection] = []

    result = edit_pdf_in_place(src, original, proposed, out)
    for outcome in result.skipped:
        rejections.append(Rejection(outcome.line_id, "layout", outcome.reason))
    applied = {o.line_id: proposed[o.line_id] for o in result.applied}
    check = check_edited_pdf(src, out, original, applied, result)
    if check.ok:
        return applied, result, check, rejections

    # The set as a whole failed. Find out which edits are at fault by adding them one at a time.
    logger.warning("pdf_edit_set_failed_check", problems=check.problems[:3])
    kept: dict[str, str] = {}
    best: tuple[PdfEditResult, PdfCheck] | None = None
    with tempfile.TemporaryDirectory() as scratch:
        trial_path = Path(scratch) / "trial.pdf"
        for line_id in applied:
            trial = {**kept, line_id: applied[line_id]}
            trial_result = edit_pdf_in_place(src, original, trial, trial_path)
            trial_applied = {o.line_id: trial[o.line_id] for o in trial_result.applied}
            trial_check = check_edited_pdf(src, trial_path, original, trial_applied, trial_result)
            if trial_check.ok and line_id in trial_applied:
                kept = trial
                best = (trial_result, trial_check)
                shutil.copyfile(trial_path, out)
            else:
                detail = "; ".join(trial_check.problems[:2]) or "failed the PDF checks"
                rejections.append(Rejection(line_id, "pdf_check", detail))
    if best is None:
        shutil.copyfile(src, out)
        empty = PdfEditResult(out, [])
        return {}, empty, check_edited_pdf(src, out, original, {}, empty), rejections
    return kept, best[0], best[1], rejections


def _language_flags(before: str, after: str) -> list[str]:
    """Machine-sounding phrases an edit introduced that the original line did not have."""
    low_before, low_after = before.lower(), after.lower()
    return [p for p in BANNED_PHRASES if p in low_after and p not in low_before]


def _focus_terms(score_: AtsScore, trusted: Sequence[TrustedSource] = ()) -> list[str]:
    """Requirements worth another round.

    Two kinds: present but only listed or only in other words, and absent from the résumé though
    trusted evidence (the profile, other résumés, the owner's declared experience) states them.
    The second kind is how a capability the CV left out is recovered.
    """
    from app.core.ats_engine.taxonomy import ReqTier, Strength

    ev = score_.evaluation
    if ev is None:
        return []
    known = chr(10).join(t.text for t in trusted).lower()
    out: list[str] = []
    for a in ev.assessments:
        if a.requirement.tier not in (ReqTier.CRITICAL, ReqTier.IMPORTANT) or a.requirement.family:
            continue
        term = a.requirement.term
        if a.strength is Strength.MENTIONED or (
            a.strength is Strength.SUPPORTED and a.match == "semantic"
        ):
            out.append(term)
        elif (
            a.strength is Strength.NONE
            and term.lower() in known
            and not excluded_terms_added("", term)
        ):
            out.append(term)
    return out[:12]


def _result_for(path: Path, edit: PdfEditResult, applied: dict[str, str]) -> PdfEditResult:
    """An edit result describing the cumulative change set, for the whole-file check."""
    return PdfEditResult(
        path, [o for o in edit.outcomes if o.status == "applied" and o.line_id in applied]
    )


async def _fit_pagination(
    out: Path,
    *,
    llm: Any | None,
    spec: Any,
    target: int,
    changes: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], dict[str, ProposedEdit]]:
    """Make ``out`` obey the pagination rules, in place. Returns the report, the line texts the
    fit changed (a removed bullet is the empty string) and the audit edits describing them."""
    applied: dict[str, str] = {}
    edits: dict[str, ProposedEdit] = {}
    try:
        with tempfile.TemporaryDirectory() as scratch:
            fit = await fit_pagination(
                out,
                Path(scratch) / "fit.pdf",
                llm=llm,
                protected_terms=spec.terms(),
                spec=spec,
                score_floor=target,
            )
            if fit.changed:
                shutil.copyfile(fit.path, out)
    except Exception as exc:  # the layout fit is an improvement; never a reason to fail
        logger.warning("pdf_pagination_fit_failed", exc_info=True)
        return {"status": "skipped", "reason": str(exc)}, applied, edits
    pagination = {"status": fit.status, **fit.report}
    for lid, old_text in fit.suppressed.items():
        applied[lid] = ""
        edits[lid] = ProposedEdit(
            line_id=lid,
            action="tweak",
            after_text="",
            reason=(
                "Removed: of the bullets that could go, it adds least to this job's match, and "
                "Education and Work have to share one page."
            ),
            evidence=old_text,
            keywords_added=[],
            level="1_clarity",
        )
    for lid, (old_text, shorter) in fit.condensed.items():
        applied[lid] = shorter
        held = changes.get(lid)
        edits[lid] = ProposedEdit(
            line_id=lid,
            action="tweak",
            after_text=shorter,
            reason=(
                (held.reason + " Then shortened" if held else "Shortened")
                + " (words removed only) so Education and Work fit on one page."
            ),
            evidence=held.evidence if held else old_text,
            keywords_added=[],
            level="1_clarity",
        )
    return pagination, applied, edits


async def tailor_pdf(
    src: Path | str,
    out: Path | str,
    *,
    job_text: str,
    job_title: str = "",
    llm: Any | None = None,
    trusted: Sequence[TrustedSource] = (),
    target: int = ATS_TARGET,
    max_rounds: int = MAX_ROUNDS,
) -> PdfTailoring:
    src, out = Path(src), Path(out)
    trusted = with_declared(tuple(trusted), job_text, job_title)
    try:
        original = build_document(str(src))
    except Exception as exc:
        raise GenerationError(f"The base résumé PDF could not be read: {exc}") from exc
    if not original.bullets():
        raise GenerationError(
            "This PDF has no editable bullets or summary the tailoring pass can work with."
        )

    spec = None
    applied: dict[str, str] = {}
    changes: dict[str, Any] = {}  # line id -> the audit change that produced it
    rejected: list[Rejection] = []
    recovery: dict[str, tuple[list[str], list[str]]] = {}
    failures: list[str] = []
    rounds: list[dict[str, Any]] = []
    base_score: AtsScore | None = None
    current_src, current_doc = src, original
    current_score: AtsScore | None = None
    last_edit = PdfEditResult(src, [])
    last_check: PdfCheck | None = None
    all_outcomes: dict[str, Any] = {}
    proposed_text: dict[str, str] = {}

    with tempfile.TemporaryDirectory() as scratch:
        # Round one is already told what the posting wants that the résumé shows weakly or not at
        # all but trusted evidence supports, so the first plan can recover it.
        focus: list[str] = []
        try:
            base_score = score(original, parse_job(job_text, title=job_title), pdf=src)
            current_score = base_score
            focus = _focus_terms(base_score, trusted)
        except Exception:  # a guide for the planner only; never a reason to fail
            base_score = current_score = None
            logger.warning("pdf_tailor_initial_focus_failed", exc_info=True)
        for round_no in range(1, max(1, max_rounds) + 1):
            try:
                result = await tailor(
                    current_doc,
                    job_text,
                    job_title=job_title,
                    llm=llm,
                    allow_reorder=False,
                    trusted=trusted,
                    exclude=frozenset(applied),
                    focus=focus,
                )
            except PlanningFailed:
                if round_no == 1:
                    raise  # nothing has been produced yet: report the failure, do not fake a result
                rounds.append(
                    {
                        "round": round_no,
                        "focus": list(focus),
                        "proposed": 0,
                        "outcome": "the language model did not answer; the earlier rounds stand",
                    }
                )
                break
            spec = result.spec
            if base_score is None:
                base_score = score(original, spec, pdf=src)
                current_score = base_score
            rejected.extend(result.audit.rejected_edits)
            failures = list(result.audit.document_failures)
            proposed = {c.line_id: c.after_text for c in result.audit.changes}
            proposed_text.update(proposed)
            entry: dict[str, Any] = {
                "round": round_no,
                "focus": list(focus),
                "proposed": len(proposed),
            }
            if not proposed:
                entry["outcome"] = "no further edits the evidence supports"
                rounds.append(entry)
                break

            step_out = Path(scratch) / f"round{round_no}.pdf"
            step_applied, step_edit, step_check, layout_rejections = _place(
                current_src, current_doc, proposed, step_out
            )
            if not step_check.ok:
                raise GenerationError(
                    "The tailored PDF failed validation: " + "; ".join(step_check.problems[:3])
                )
            entry["applied"] = len(step_applied)
            if not step_applied:
                rejected.extend(layout_rejections)
                entry["outcome"] = "no edit fitted the page"
                rounds.append(entry)
                break

            step_doc = build_document(str(step_out))
            step_score = score(step_doc, spec, pdf=step_out)
            entry["ats_after"] = step_score.total
            assert current_score is not None
            if round_no > 1 and step_score.total <= current_score.total:
                entry["outcome"] = "did not raise the score; discarded"
                rounds.append(entry)
                break

            entry["outcome"] = "kept"
            rounds.append(entry)
            rejected.extend(layout_rejections)
            for line_id, text in step_applied.items():
                applied[line_id] = text
                changes[line_id] = next(c for c in result.audit.changes if c.line_id == line_id)
            for outcome in step_edit.outcomes:
                if outcome.status == "applied":
                    all_outcomes[outcome.line_id] = outcome
            recovery.update({lid: v for lid, v in result.recovery.items() if lid in step_applied})
            last_check = step_check
            current_src, current_doc, current_score = step_out, step_doc, step_score
            shutil.copyfile(step_out, out)
            if step_score.total >= target:
                break
            focus = _focus_terms(step_score, trusted)
            if not focus:
                break

    last_edit = PdfEditResult(out, list(all_outcomes.values()))
    if not applied:
        shutil.copyfile(src, out)
        last_check = check_edited_pdf(src, out, original, {}, last_edit)
    else:
        # The whole change set is checked once more against the original, not just step by step.
        last_check = check_edited_pdf(src, out, original, applied, last_edit)
    if not last_check.ok:
        raise GenerationError(
            "The tailored PDF failed validation: " + "; ".join(last_check.problems[:3])
        )

    # Pagination rules: re-flow, then shorten, then (only if it must) remove the bullets that add
    # least to the job. This applies to every file, edited or not: the owner's layout rules are not
    # optional, and a file that needed no wording changes can still need a page break moved.
    assert spec is not None
    pagination, extra_applied, condensed_edits = await _fit_pagination(
        out, llm=llm, spec=spec, target=target, changes=changes
    )
    applied.update(extra_applied)

    expected = _expected_document(original, applied)
    final = build_document(str(out))
    structure_ok = final.fingerprint() == original.fingerprint()
    if not structure_ok:
        raise GenerationError(
            "The tailored PDF no longer has the same headings and fixed lines as the original."
        )

    before = base_score or score(original, spec, pdf=src)
    after = score(final, spec, pdf=out)
    reverted = ""
    wording_edits = any(lid in changes for lid in applied)
    # What the wording edits alone scored, before any bullet was removed for the page rule.
    wording_total = current_score.total if current_score is not None else before.total
    if wording_edits and wording_total < before.total:
        # Never ship a résumé that matches the job worse than the one it started as.
        reverted = (
            f"Tailoring lowered the ATS match ({before.total} to {wording_total}); "
            "the original wording is kept."
        )
        shutil.copyfile(src, out)
        changes, recovery = {}, {}
        last_edit = PdfEditResult(out, [])
        last_check = check_edited_pdf(src, out, original, {}, last_edit)
        pagination, applied, condensed_edits = await _fit_pagination(
            out, llm=llm, spec=spec, target=target, changes={}
        )
        expected = _expected_document(original, applied)
        final = build_document(str(out))
        after = score(final, spec, pdf=out)

    fit_removed = [lid for lid, text in applied.items() if text == ""]
    accepted = [
        ProposedEdit(
            line_id=lid,
            action="tweak",
            after_text=text,
            reason=changes[lid].reason,
            evidence=changes[lid].evidence,
            keywords_added=list(changes[lid].keywords_added),
            level=changes[lid].level,
        )
        for lid, text in applied.items()
        if lid in changes and lid not in condensed_edits
    ] + list(condensed_edits.values())
    audit = build_audit(
        original=original,
        tailored=expected,
        accepted=accepted,
        rejected=rejected,
        before_score=before,
        after_score=after,
        reordered=[],
        document_failures=failures,
        job_title=job_title or spec.title,
        recovery=recovery,
    )

    language = {c.line_id: _language_flags(c.before_text, c.after_text) for c in audit.changes}
    invented = {
        c.line_id: sorted(_numbers(c.after_text) - _numbers(c.before_text)) for c in audit.changes
    }
    evaluation = after.evaluation
    limit = evaluation.verdict.tailoring_limit if evaluation is not None else ""
    note = reverted or (
        ""
        if after.total >= target
        else limit
        or f"The score is {after.total}, below the {target} target: the remaining gaps are "
        "requirements "
        "the résumé has no evidence for, and adding them would be fabrication."
    )
    layout_cost = (before.total if reverted else wording_total) - after.total
    if pagination.get("status") == "suppressed" and layout_cost > 0:
        note = (
            f"Removing {len(fit_removed)} bullet(s) so Education and Work share one page cost "
            f"{layout_cost} ATS point(s). " + note
        ).strip()
    details = {
        "mode": "pdf_in_place",
        "formatting_preserved": True,
        "applied": [o.line_id for o in last_edit.applied],
        "skipped": [
            {
                "line_id": r.line_id,
                "reason": r.detail,
                "proposed_chars": len(proposed_text.get(r.line_id, "")),
                "max_chars": original.capacity.get(r.line_id),
            }
            for r in rejected
            if r.rule == "layout"
        ],
        "substituted_fonts": sorted({f for o in last_edit.applied for f in o.substituted_fonts}),
        "checks": {"ok": last_check.ok, "problems": last_check.problems, **last_check.metrics},
        "structure_unchanged": structure_ok,
        "recovered_from_trusted_evidence": {
            c.line_id: {"terms": c.recovered_terms, "sources": c.evidence_sources}
            for c in audit.changes
            if c.recovered_terms
        },
        "trusted_sources_consulted": [t.label for t in trusted],
        "ats_scored_from": "generated_pdf",
        "ats_target": target,
        "ats_target_reached": after.total >= target,
        "ats_target_note": note,
        "ats_cost_of_layout": max(0, layout_cost),
        "rounds": rounds,
        "pagination": pagination,
        "evaluation_before": before.evaluation.to_dict() if before.evaluation else None,
        "evaluation_after": after.evaluation.to_dict() if after.evaluation else None,
        "language_flags": {k: v for k, v in language.items() if v},
        "introduced_numbers": {k: v for k, v in invented.items() if v},
    }
    laid_out = pagination.get("status") in ("reflowed", "condensed", "suppressed")
    status = "generated" if (audit.changes or laid_out) else "unchanged"
    return PdfTailoring(
        status=status,
        path=out,
        original=original,
        expected=expected,
        final=final,
        audit=audit,
        before=before,
        after=after,
        edit=last_edit,
        check=last_check,
        details=details,
    )
