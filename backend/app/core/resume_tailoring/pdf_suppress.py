"""Cut the bullets that add least to the job, when Education and Work cannot otherwise share a page.

The owner's brief asks for ruthless suppression of anything that does not raise interview
probability, and their pagination rule asks for Education and Work on one page. When re-flowing and
shortening wording are not enough, whole bullets have to go. This module chooses which, by how
little the job-match score cares about them, and removes them from the page.

What it will not do:

* remove the last bullet of a project or role: every heading keeps something under it;
* remove a bullet whose loss would leave a critical requirement with no evidence at all;
* lower the ATS match below the target, or, if the posting is already out of reach of it, by more
  than a few points in total.

Removed text is reported in the change log as ``removed`` with the line it was, so nothing leaves the
résumé silently.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.core.resume_tailoring.evidence import AtsScore, score
from app.core.resume_tailoring.jobspec import JobSpec
from app.core.resume_tailoring.model import LineKind, ResumeDocument
from app.core.resume_tailoring.pdf_paginate import Pagination, Row, section_role
from app.core.resume_tailoring.pdf_reflow import Shrink

logger = structlog.get_logger(__name__)

#: Points of ATS match that may be given up to meet the page rule when the target is out of reach.
_BELOW_TARGET_ALLOWANCE = 4


@dataclass
class Cut:
    line_id: str
    text: str
    score_after: int
    #: Points of page the removal gives back (the paragraph and the gap that followed it).
    freed: float


def without(doc: ResumeDocument, ids: set[str]) -> ResumeDocument:
    copy = doc.copy()
    for section in copy.sections:
        section.lines = [ln for ln in section.lines if ln.id not in ids]
    return copy


def _strengths(result: AtsScore) -> dict[str, int]:
    ev = result.evaluation
    if ev is None:
        return {}
    return {
        a.requirement.term: int(a.strength)
        for a in ev.assessments
        if a.requirement.tier.name == "CRITICAL"
    }


def _groups(doc: ResumeDocument) -> dict[str, list[str]]:
    """Line id -> ids of the removable bullets under the same project or role heading."""
    out: dict[str, list[str]] = {}
    for section in doc.sections:
        if section_role(section.heading) != "work":
            continue
        run: list[str] = []
        for line in [*section.lines, None]:
            if line is not None and line.kind is LineKind.BULLET:
                run.append(line.id)
                continue
            for lid in run:
                out[lid] = list(run)
            run = []
    return out


def _paragraph_rows(pagination: Pagination, par: Any) -> list[Row]:
    first = par.lines[0].bbox
    rows = [r for r in pagination.rows if r.kind == "text" and r.paragraph is not None]
    owner = next(
        (
            r.paragraph
            for r in rows
            if r.page == par.page
            and r.paragraph.lines
            and all(abs(a - b) < 0.5 for a, b in zip(r.paragraph.lines[0].bbox, first, strict=True))
        ),
        None,
    )
    return [r for r in rows if r.paragraph is owner] if owner is not None else []


def plan_cuts(
    doc: ResumeDocument,
    pagination: Pagination,
    spec: JobSpec,
    *,
    deficit: float,
    floor: int,
) -> list[Cut]:
    """Bullets to remove, least valuable first, until their combined height covers ``deficit``."""
    base = score(doc, spec)
    # Above the target, a cut may not take the match under it. Already below it (an honest
    # ceiling for this posting), a few points may go to meet the page rule, and no more.
    lowest = floor if base.total >= floor else base.total - _BELOW_TARGET_ALLOWANCE
    groups = _groups(doc)
    base_strength = _strengths(base)
    gaps = [
        b.top - a.bottom
        for a, b in zip(pagination.rows, pagination.rows[1:], strict=False)
        if a.page == b.page and a.kind == b.kind == "text" and 0 <= b.top - a.bottom < 30
    ]
    gap = statistics.median(gaps) if gaps else 2.0

    removed: set[str] = set()
    cuts: list[Cut] = []
    freed = 0.0
    current = base
    while freed < deficit + 2:
        best: tuple[tuple[int, int, int, float], Cut] | None = None
        for lid, group in groups.items():
            par = doc.layout.get(lid)
            if lid in removed or par is None or len([g for g in group if g not in removed]) < 2:
                continue
            rows = _paragraph_rows(pagination, par)
            if not rows:
                continue
            trial = score(without(doc, removed | {lid}), spec)
            if trial.total < lowest:
                continue  # would cost the match more than the page rule is worth
            now = _strengths(trial)
            lost = sum(1 for t, s in base_strength.items() if now.get(t, 0) < s)
            if lost and any(now.get(t, 0) == 0 < s for t, s in base_strength.items()):
                continue  # a requirement the résumé evidences would become unevidenced
            height = sum(r.height for r in rows) + gap * len(rows)
            key = (lost, current.total - trial.total, -len(rows), -height)
            line = next(ln for ln in doc.bullets() if ln.id == lid)
            cut = Cut(lid, line.text, trial.total, height)
            if best is None or key < best[0]:
                best = (key, cut)
        if best is None:
            return []  # nothing can go without costing more than it saves
        cut = best[1]
        removed.add(cut.line_id)
        cuts.append(cut)
        freed += cut.freed
        current = score(without(doc, removed), spec)
    logger.info("pdf_suppress_planned", cuts=[c.line_id for c in cuts], freed=round(freed, 1))
    return cuts


def shrink_for(pagination: Pagination, doc: ResumeDocument, ids: list[str]) -> Shrink:
    """The page-space the removals leave, keyed the way the re-flow expects it.

    A removed paragraph leaves a hole between the last row above it and the first row below. The
    re-flow is told how much of the gap after the surviving row above was vacated, so it closes it.
    """
    rows = sorted(pagination.rows, key=lambda r: (r.page, r.top))
    dead: set[int] = set()
    shrink: Shrink = {}
    for lid in sorted(ids, key=lambda i: (doc.layout[i].page, doc.layout[i].bbox[1])):
        par = doc.layout[lid]
        mine = _paragraph_rows(pagination, par)
        if not mine:
            continue
        first, last = rows.index(mine[0]), rows.index(mine[-1])
        dead.update(id(r) for r in mine)
        if last + 1 >= len(rows) or rows[last + 1].page != mine[0].page:
            continue
        hole = rows[last + 1].top - mine[0].top
        k = first - 1
        while k >= 0 and id(rows[k]) in dead:
            k -= 1
        if k < 0 or rows[k].page != mine[0].page:
            continue
        key = (rows[k].page, rows[k].baseline)
        shrink[key] = shrink.get(key, 0.0) + hole
    return shrink


def apply_cuts(src: Path, doc: ResumeDocument, cuts: list[Cut], out: Path):
    from app.core.resume_tailoring.pdf_check import check_edited_pdf
    from app.core.resume_tailoring.pdf_edit import edit_pdf_in_place

    edits = {c.line_id: "" for c in cuts}
    result = edit_pdf_in_place(src, doc, edits, out)
    applied = {o.line_id: "" for o in result.applied}
    check = check_edited_pdf(src, out, doc, applied, result)
    return applied, result, check
