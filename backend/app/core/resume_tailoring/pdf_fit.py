"""Make a tailored PDF obey the pagination rules: re-flow it, and shorten bullets only if it must.

Order of remedies, least invasive first, each verified before it is kept:

1. Already compliant: nothing is touched.
2. Re-flow (``pdf_reflow``): move whole lines and separators between and within pages. No wording
   changes and every moved line is checked to be identical.
3. Condense: when Education + Work simply do not fit one page, ask for the same bullets in fewer
   words (``condense``: words may only be removed), place them in the PDF, then re-flow.
4. Suppress (``pdf_suppress``): if that is still not enough and a job posting is known, remove the
   bullets that add least to the job-match score, never the last under a heading and never one the
   match depends on, then re-flow. The owner's brief asks for exactly this cut.

If the rules still cannot be met, the PDF is left as it was and the shortfall is reported in
points and lines.
"""

from __future__ import annotations

import math
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from app.core.resume_tailoring import condense, pdf_suppress
from app.core.resume_tailoring.pdf_check import check_edited_pdf
from app.core.resume_tailoring.pdf_edit import edit_pdf_in_place
from app.core.resume_tailoring.pdf_layout import build_document
from app.core.resume_tailoring.pdf_paginate import analyse, section_role
from app.core.resume_tailoring.pdf_reflow import Shrink, fit_deficit, reflow_to_rules

logger = structlog.get_logger(__name__)

MAX_CONDENSE_ROUNDS = 3
_MAX_TARGETS = 16


@dataclass
class FitOutcome:
    #: "compliant" | "reflowed" | "condensed" | "not_met" | "skipped"
    status: str
    path: Path
    report: dict[str, Any] = field(default_factory=dict)
    #: line id -> (text before, text after) for bullets shortened to make the layout fit.
    condensed: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: line id -> the text of a bullet removed to make the layout fit.
    suppressed: dict[str, str] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.status in ("reflowed", "condensed", "suppressed")


def _targets(path: Path) -> list[condense.CondenseTarget]:
    """Work-section bullets that wrap onto several lines, easiest to shorten first."""
    doc = build_document(str(path))
    out: list[condense.CondenseTarget] = []
    for section in doc.sections:
        if section_role(section.heading) != "work":
            continue
        for line in section.lines:
            par = doc.layout.get(line.id)
            if not line.editable or par is None or len(par.lines) < 2:  # type: ignore[attr-defined]
                continue
            out.append(
                condense.CondenseTarget(
                    line.id,
                    line.text,
                    len(par.lines),
                    len(par.lines[-1].text),  # type: ignore[attr-defined]
                )
            )
    out.sort(key=lambda t: t.last_line_chars)
    return out[:_MAX_TARGETS]


def _summary(p: Any) -> dict[str, Any]:
    return p.to_dict()


async def fit_pagination(
    current: Path | str,
    out: Path | str,
    *,
    llm: Any | None = None,
    protected_terms: Iterable[str] = (),
    max_rounds: int = MAX_CONDENSE_ROUNDS,
    spec: Any | None = None,
    score_floor: int = 0,
) -> FitOutcome:
    """Write the best pagination-compliant version of ``current`` to ``out``."""
    current, out = Path(current), Path(out)
    try:
        before = analyse(current)
    except Exception as exc:
        shutil.copyfile(current, out)
        return FitOutcome("skipped", out, {"reason": f"The PDF could not be analysed: {exc}"})
    report: dict[str, Any] = {"before": _summary(before)}
    if before.ok:
        shutil.copyfile(current, out)
        report["after"] = report["before"]
        return FitOutcome("compliant", out, report)

    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        reflowed = reflow_to_rules(current, work / "reflow.pdf")
        report["reflow"] = {
            "applied": reflowed.applied,
            "reason": reflowed.reason,
            "problems": reflowed.problems,
        }
        if reflowed.applied:
            shutil.copyfile(work / "reflow.pdf", out)
            report["after"] = _summary(reflowed.after)  # type: ignore[arg-type]
            return FitOutcome("reflowed", out, report)

        deficit = fit_deficit(before)
        report["deficit_points"] = round(deficit[0], 1) if deficit else None
        if not (deficit and deficit[0] > 0):
            shutil.copyfile(current, out)
            report["after"] = report["before"]
            return FitOutcome("not_met", out, report)

        if llm is not None:
            condensed, _shrink, path = await _condense_rounds(
                current, work, llm, list(protected_terms), max_rounds, report
            )
            if path is not None:
                shutil.copyfile(path, out)
                report["after"] = _summary(analyse(out))
                return FitOutcome("condensed", out, report, condensed)

        if spec is not None:
            cut = _suppress(current, work, before, deficit, spec, score_floor, report)
            if cut is not None:
                path, suppressed = cut
                shutil.copyfile(path, out)
                report["after"] = _summary(analyse(out))
                return FitOutcome("suppressed", out, report, suppressed=suppressed)

    shutil.copyfile(current, out)
    report["after"] = report["before"]
    return FitOutcome("not_met", out, report)


async def _condense_rounds(
    current: Path,
    work: Path,
    llm: Any,
    protected: list[str],
    max_rounds: int,
    report: dict[str, Any],
) -> tuple[dict[str, tuple[str, str]], Shrink, Path | None]:
    """Shorten bullets round by round until the rules can be met. Nothing is kept on failure."""
    path = current
    shrink: Shrink = {}
    condensed: dict[str, tuple[str, str]] = {}
    rounds: list[dict[str, Any]] = []
    report["condense_rounds"] = rounds
    for round_no in range(1, max_rounds + 1):
        pagination = analyse(path)
        deficit = fit_deficit(pagination, shrink)
        if deficit is None or deficit[0] <= 0:
            break
        lines_needed = max(1, math.ceil((deficit[0] + 2) / deficit[1]))
        targets = [t for t in _targets(path) if t.line_id not in condensed]
        proposals = await condense.propose(llm, targets, lines_needed, protected)
        entry: dict[str, Any] = {
            "round": round_no,
            "lines_needed": lines_needed,
            "proposed": len(proposals),
        }
        rounds.append(entry)
        if not proposals:
            entry["outcome"] = "no safe shortening was available"
            break
        doc = build_document(str(path))
        step = work / f"condense{round_no}.pdf"
        result = edit_pdf_in_place(path, doc, proposals, step)
        applied = {o.line_id: proposals[o.line_id] for o in result.applied}
        check = check_edited_pdf(path, step, doc, applied, result)
        if not applied or not check.ok:
            entry["outcome"] = "the shortened text could not be placed cleanly"
            break
        before_text = {t.line_id: t.text for t in targets}
        for outcome in result.applied:
            if outcome.shrink > 0:
                par = doc.layout[outcome.line_id]
                key = (outcome.page, round(par.lines[outcome.new_lines - 1].baseline, 1))  # type: ignore[attr-defined]
                shrink[key] = outcome.shrink
            condensed[outcome.line_id] = (before_text[outcome.line_id], applied[outcome.line_id])
        entry["applied"] = len(applied)
        entry["lines_saved"] = sum(o.old_lines - o.new_lines for o in result.applied)
        final = work / f"fit{round_no}.pdf"
        reflowed = reflow_to_rules(step, final, shrink=shrink, force=True)
        if reflowed.applied:
            entry["outcome"] = "fits"
            return condensed, shrink, final
        entry["outcome"] = f"still short: {reflowed.reason}"
        path = step
    return {}, {}, None


def _suppress(
    current: Path,
    work: Path,
    before: Any,
    deficit: tuple[float, float],
    spec: Any,
    floor: int,
    report: dict[str, Any],
) -> tuple[Path, dict[str, str]] | None:
    """Remove the least valuable bullets and re-flow. Nothing is kept unless the rules are met."""
    entry: dict[str, Any] = {}
    report["suppress"] = entry
    doc = build_document(str(current))
    cuts = pdf_suppress.plan_cuts(doc, before, spec, deficit=deficit[0], floor=floor)
    entry["planned"] = [c.line_id for c in cuts]
    if not cuts:
        entry["outcome"] = "no bullet could be removed without costing more than it saves"
        return None
    step = work / "suppress.pdf"
    applied, _result, check = pdf_suppress.apply_cuts(current, doc, cuts, step)
    if not applied or not check.ok:
        entry["outcome"] = "the removal could not be done cleanly: " + "; ".join(check.problems[:2])
        return None
    shrink = pdf_suppress.shrink_for(before, doc, list(applied))
    final = work / "suppress_fit.pdf"
    reflowed = reflow_to_rules(step, final, shrink=shrink, force=True)
    if not reflowed.applied:
        entry["outcome"] = f"still short after removing {len(applied)}: {reflowed.reason}"
        entry["problems"] = list(reflowed.problems)[:4]
        return None
    entry["outcome"] = "fits"
    entry["score_after"] = cuts[-1].score_after
    by_id = {c.line_id: c.text for c in cuts}
    return final, {lid: by_id[lid] for lid in applied}
