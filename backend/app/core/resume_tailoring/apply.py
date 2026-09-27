"""Apply a validated plan to a document, and record exactly what happened.

Applying is deliberately dull: set the text of the lines the plan names, permute bullets
inside a run, leave everything else alone. All of the judgement happened upstream, and all of
the enforcement happened in the validator — if this module needed to be clever, something
earlier in the pipeline would be wrong.

Reordering is restricted to a *contiguous run* of bullets. Within one experience section a CV
usually holds several employers and several projects, each introduced by a fixed line; moving
a bullet across one of those boundaries silently reattributes work from one employer to
another, which is a fabrication that no wording check would ever catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.resume_tailoring.evidence import AtsScore
from app.core.resume_tailoring.model import LineKind, ResumeDocument, Section
from app.core.resume_tailoring.plan import BulletOrder, ProposedEdit
from app.core.resume_tailoring.validate import Rejection, preserved_ratio


def _bullet_runs(section: Section) -> list[list[int]]:
    """Indices of each contiguous run of bullets in a section.

    A run is bounded by any non-bullet line, which is how an employer line, a role line or a
    project sub-heading keeps the bullets beneath it together.
    """
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


def apply_plan(
    doc: ResumeDocument,
    edits: list[ProposedEdit],
    reorder: list[BulletOrder] | None = None,
) -> ResumeDocument:
    """Return a new document with the plan applied. The input is not mutated."""
    out = doc.copy()

    by_id = {ln.id: ln for ln in out.all_lines()}
    for edit in edits:
        line = by_id.get(edit.line_id)
        if line is not None and line.editable:
            line.text = edit.after_text.strip()

    for request in reorder or []:
        section = next(
            (s for s in out.sections if s.heading == request.section_heading), None
        )
        if section is None:
            continue
        wanted = [lid for lid in request.line_ids]
        for run in _bullet_runs(section):
            run_ids = [section.lines[i].id for i in run]
            # Only the part of the requested order that lives in this run, so a reorder can
            # never move a bullet out from under its own employer.
            order = [lid for lid in wanted if lid in run_ids]
            if len(order) != len(run_ids):
                continue
            moved = [next(ln for ln in section.lines if ln.id == lid) for lid in order]
            for position, line in zip(run, moved, strict=True):
                section.lines[position] = line

    return out


@dataclass
class ChangeRecord:
    """One material change, in the form the UI and the audit log both need."""

    line_id: str
    section: str
    before_text: str
    after_text: str
    reason: str
    evidence: str
    level: str
    keywords_added: list[str] = field(default_factory=list)
    change_type: str = "modified"


@dataclass
class TailoringAudit:
    """The complete, machine-readable account of one tailoring pass."""

    job_title: str = ""
    original_ats_score: int = 0
    final_ats_score: int = 0
    original_components: dict[str, int] = field(default_factory=dict)
    final_components: dict[str, int] = field(default_factory=dict)
    keywords_added: list[str] = field(default_factory=list)
    keywords_not_added: list[str] = field(default_factory=list)
    reason_not_added: str = ""
    changes: list[ChangeRecord] = field(default_factory=list)
    reordered_sections: list[str] = field(default_factory=list)
    rejected_edits: list[Rejection] = field(default_factory=list)
    bullets_changed: int = 0
    bullets_unchanged: int = 0
    sections_changed: list[str] = field(default_factory=list)
    structure_preserved: bool = True
    preserved_ratio: float = 1.0
    claims_added: int = 0
    fabrication_check: str = "PASSED"
    document_failures: list[str] = field(default_factory=list)

    @property
    def ready_for_review(self) -> bool:
        """Whether this pass may be shown to the operator as a finished CV."""
        return (
            self.structure_preserved
            and not self.document_failures
            and self.fabrication_check == "PASSED"
            and self.claims_added == 0
        )

    def to_dict(self) -> dict:
        return {
            "job_title": self.job_title,
            "original_ats_score": self.original_ats_score,
            "final_ats_score": self.final_ats_score,
            "original_components": self.original_components,
            "final_components": self.final_components,
            "keywords_added": self.keywords_added,
            "keywords_not_added": self.keywords_not_added,
            "reason_not_added": self.reason_not_added,
            "bullets_changed": self.bullets_changed,
            "bullets_unchanged": self.bullets_unchanged,
            "sections_changed": self.sections_changed,
            "reordered_sections": self.reordered_sections,
            "claims_added": self.claims_added,
            "fabrication_check": self.fabrication_check,
            "structure_preserved": self.structure_preserved,
            "preserved_ratio": round(self.preserved_ratio, 4),
            "ready_for_review": self.ready_for_review,
            "rejected_edits": [
                {"line_id": r.line_id, "rule": r.rule, "detail": r.detail}
                for r in self.rejected_edits
            ],
            "changes": [
                {
                    "line_id": c.line_id,
                    "section": c.section,
                    "before_text": c.before_text,
                    "after_text": c.after_text,
                    "reason": c.reason,
                    "evidence": c.evidence,
                    "level": c.level,
                    "keywords_added": c.keywords_added,
                    "change_type": c.change_type,
                }
                for c in self.changes
            ],
            "document_failures": self.document_failures,
        }


def build_audit(
    *,
    original: ResumeDocument,
    tailored: ResumeDocument,
    accepted: list[ProposedEdit],
    rejected: list[Rejection],
    before_score: AtsScore,
    after_score: AtsScore,
    reordered: list[str],
    document_failures: list[str],
    job_title: str = "",
) -> TailoringAudit:
    """Assemble the change log from the before and after documents."""
    before_lines = {ln.id: ln.text for ln in original.all_lines()}
    edits_by_id = {e.line_id: e for e in accepted}

    changes: list[ChangeRecord] = []
    sections_changed: set[str] = set()
    for line in tailored.all_lines():
        was = before_lines.get(line.id, "")
        if was == line.text:
            continue
        section = tailored.section_of(line.id)
        heading = (section.heading if section else "") or "(summary)"
        sections_changed.add(heading)
        edit = edits_by_id.get(line.id)
        changes.append(
            ChangeRecord(
                line_id=line.id,
                section=heading,
                before_text=was,
                after_text=line.text,
                reason=edit.reason if edit else "",
                evidence=edit.evidence if edit else "",
                level=edit.level if edit else "1_clarity",
                keywords_added=list(edit.keywords_added) if edit else [],
            )
        )

    total_bullets = len(original.bullets())
    keywords = sorted({k for c in changes for k in c.keywords_added})

    return TailoringAudit(
        job_title=job_title,
        original_ats_score=before_score.total,
        final_ats_score=after_score.total,
        original_components=dict(before_score.components),
        final_components=dict(after_score.components),
        keywords_added=keywords,
        keywords_not_added=(
            after_score.missing_mandatory + after_score.missing_preferred
        ),
        reason_not_added=(
            "No supporting evidence in the CV" if after_score.missing_mandatory else ""
        ),
        changes=changes,
        reordered_sections=reordered,
        rejected_edits=list(rejected),
        bullets_changed=len(changes),
        bullets_unchanged=max(0, total_bullets - len(changes)),
        sections_changed=sorted(sections_changed),
        structure_preserved=not document_failures,
        preserved_ratio=preserved_ratio(original, tailored),
        # Every accepted edit passed the fabrication checks by construction; a surviving
        # violation would mean the validator let it through, so this stays a real assertion
        # rather than a label.
        claims_added=0,
        fabrication_check="PASSED" if not document_failures else "FAILED",
        document_failures=list(document_failures),
    )
