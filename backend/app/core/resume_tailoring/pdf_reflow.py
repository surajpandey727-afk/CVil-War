"""Move a PDF's content between and within pages to satisfy the pagination rules, losslessly.

Nothing is redrawn and no wording changes. The layout is re-flowed by *moving* the drawn pieces
(see ``pdf_atoms``): a stranded separator travels to the page its heading is on, Extra-Curricular
starts on a fresh page, a heading that would be left at the foot of a page goes with its first
lines. Gaps between pieces are the gaps the document already had, so the result keeps the
original spacing system.

A re-flow is only kept if the result passes every hard rule *and* every moved line renders
exactly as it did before; otherwise the original file is returned untouched and the reason is
reported. A layout that cannot be reached without removing content is reported, not forced.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

from app.core.resume_tailoring import pdf_atoms as pa
from app.core.resume_tailoring import pdf_read
from app.core.resume_tailoring import pdf_stream as ps
from app.core.resume_tailoring.pdf_paginate import (
    Pagination,
    Row,
    analyse,
    evaluate_rows,
    is_separator,
)

_EPS = 0.75
_FALLBACK_GAP = 3.0
#: A paragraph this long or shorter is never split across a page break.
_KEEP_TOGETHER = 3


@dataclass
class Placement:
    row: Row
    page: int
    top: float

    @property
    def dy(self) -> float:
        return self.top - self.row.top


@dataclass
class Unit:
    rows: list[Row]
    force_break: bool = False
    #: Where each row sits below the unit's top, and how tall the unit is. Filled in by
    #: :func:`_measure`: rows that were on different pages are separated by a natural gap,
    #: not by the (meaningless) distance between their old page coordinates.
    offsets: list[float] = field(default_factory=list)
    extent: float = 0.0


@dataclass
class ReflowResult:
    ok: bool
    applied: bool
    before: Pagination
    after: Pagination | None = None
    reason: str = ""
    moved_rows: int = 0
    problems: list[str] = field(default_factory=list)


# --- planning --------------------------------------------------------------------------------


def _units(rows: list[Row], extra_heading_rows: set[int]) -> list[Unit]:
    """Group rows that must not be separated by a page break."""
    units: list[Unit] = []
    i, n = 0, len(rows)
    texts = [r for r in rows if r.kind == "text"]
    text_width = (max(r.right for r in texts) - min(r.left for r in texts)) if texts else 0.0
    while i < n:
        row = rows[i]
        if row.kind == "rule" and not is_separator(row, text_width) and units:
            units[-1].rows.append(row)  # a table border or underline stays with what it belongs to
            i += 1
            continue
        if row.kind == "rule" or row.heading:
            group: list[Row] = []
            j = i
            while j < n and rows[j].kind == "rule" and is_separator(rows[j], text_width):
                group.append(rows[j])
                j += 1
            if j < n and rows[j].heading:
                group.append(rows[j])
                j += 1
                body = 0
                while j < n and body < 2 and not rows[j].heading:
                    group.append(rows[j])
                    body += rows[j].kind == "text"
                    j += 1
            force = any(id(r) in extra_heading_rows for r in group)
            units.append(Unit(group, force))
            i = j
            continue
        par = row.paragraph
        if par is not None and row.index_in_paragraph == 0 and len(par.lines) > 1:
            members = [
                rows[i + k]
                for k in range(len(par.lines))
                if i + k < n and rows[i + k].paragraph is par
            ]
            if len(members) <= _KEEP_TOGETHER:
                units.append(Unit(members))
            else:
                units.append(Unit(members[:2]))
                units.extend(Unit([m]) for m in members[2:-2])
                units.append(Unit(members[-2:]))
            i += len(members)
            continue
        units.append(Unit([row]))
        i += 1
    return units


def _gap_stats(rows: list[Row]) -> tuple[float, float]:
    """Typical gap between text rows, and between a rule and the heading under it."""
    text_gaps: list[float] = []
    rule_gaps: list[float] = []
    for a, b in zip(rows, rows[1:], strict=False):
        if a.page != b.page:
            continue
        gap = b.top - a.bottom
        if a.kind == "text" and b.kind == "text" and not b.heading and 0 <= gap < 30:
            text_gaps.append(gap)
        if a.kind == "rule" and b.kind == "text" and b.heading and 0 <= gap < 40:
            rule_gaps.append(gap)
    return (
        statistics.median(text_gaps) if text_gaps else _FALLBACK_GAP,
        statistics.median(rule_gaps) if rule_gaps else _FALLBACK_GAP,
    )


Shrink = dict[tuple[int, float], float]


class _Gaps:
    """The vertical gaps between rows: the document's own where it has them, natural otherwise."""

    def __init__(self, rows: list[Row], shrink: Shrink | None) -> None:
        self.text, self.rule = _gap_stats(rows)
        self.shrink = shrink or {}

    def vacated(self, prev: Row) -> float:
        """Space an edited paragraph gave up below its (now earlier) last line."""
        for (page, baseline), amount in self.shrink.items():
            if page == prev.page and abs(baseline - prev.baseline) <= 0.6:
                return amount
        return 0.0

    def between(self, prev: Row, row: Row) -> float:
        if row.page == prev.page:
            return row.top - prev.bottom - self.vacated(prev)
        return self.rule if prev.kind == "rule" and row.heading else self.text


def _measure(unit: Unit, gaps: _Gaps) -> None:
    unit.offsets = [0.0]
    bottom = unit.rows[0].height
    for prev, row in zip(unit.rows, unit.rows[1:], strict=False):
        unit.offsets.append(bottom + gaps.between(prev, row))
        bottom = unit.offsets[-1] + row.height
    unit.extent = bottom


def _frame_tops(pagination: Pagination) -> tuple[float, float]:
    rows = pagination.rows
    first_tops = [
        min((r.top for r in rows if r.page == p), default=None) for p in range(pagination.pages)
    ]
    later = [t for t in first_tops[1:] if t is not None]
    top_first = first_tops[0] if first_tops and first_tops[0] is not None else pagination.frame_top
    return top_first, (statistics.median(later) if later else top_first)


def fit_deficit(pagination: Pagination, shrink: Shrink | None = None) -> tuple[float, float] | None:
    """How many points Education + Work overflow one page by, and the typical line height.

    ``None`` when the document has no such pair. Zero or negative means they already fit.
    """
    sections = [s for s in pagination.sections if s.role in ("education", "work")]
    if not any(s.role == "education" for s in sections) or not any(
        s.role == "work" for s in sections
    ):
        return None
    rows = [r for s in sections for r in s.rows]
    rows.sort(key=lambda r: (r.page, r.top, r.left))
    gaps = _Gaps(pagination.rows, shrink)
    total = rows[0].height
    for prev, row in zip(rows, rows[1:], strict=False):
        total += gaps.between(prev, row) + row.height
    _, top_later = _frame_tops(pagination)
    available = pagination.frame_bottom - top_later
    leads = [
        b.baseline - a.baseline
        for a, b in zip(rows, rows[1:], strict=False)
        if a.page == b.page and 8 < b.baseline - a.baseline < 25
    ]
    return total - available, (statistics.median(leads) if leads else 13.0)


def _block(pagination: Pagination, units: list[Unit], gaps: _Gaps) -> tuple[int | None, float]:
    """Index of the unit that opens the Education-to-Work block, and the height of the block."""
    idx = [i for i, sec in enumerate(pagination.sections) if sec.role in ("education", "work")]
    if len(idx) < 2 or not {pagination.sections[i].role for i in idx} >= {"education", "work"}:
        return None, 0.0
    lo, hi = min(idx), max(idx)
    members = {id(r) for sec in pagination.sections[lo : hi + 1] for r in sec.rows}
    indices = [k for k, u in enumerate(units) if any(id(r) in members for r in u.rows)]
    if not indices:
        return None, 0.0
    total = units[indices[0]].extent
    for a, b in zip(indices, indices[1:], strict=False):
        total += gaps.between(units[a].rows[-1], units[b].rows[0]) + units[b].extent
    return indices[0], total


def plan_layout(
    pagination: Pagination, *, break_before_extra: bool = True, shrink: Shrink | None = None
) -> list[Placement]:
    """Assign every row a page and a position, keeping groups together and original gaps."""
    rows = pagination.rows
    extra_rows: set[int] = set()
    if break_before_extra:
        for section in pagination.sections:
            if section.role == "extra":
                first_text = next((r for r in section.rows if r.kind == "text"), None)
                if first_text is not None:
                    extra_rows.add(id(first_text))
    units = _units(rows, extra_rows)
    gaps = _Gaps(rows, shrink)
    for unit in units:
        _measure(unit, gaps)
    top_first, top_later = _frame_tops(pagination)
    bottom = pagination.frame_bottom
    block_start, block_extent = _block(pagination, units, gaps)

    placements: list[Placement] = []
    page, cursor, prev = 0, None, None
    for index, unit in enumerate(units):
        first = unit.rows[0]
        if cursor is None or prev is None:
            top = top_first if page == 0 else top_later
        else:
            top = cursor + gaps.between(prev, first)
        # Education and Work are one block: if it fits a page at all, it starts where it can end.
        block_overflows = (
            index == block_start
            and top + block_extent > bottom + _EPS
            and block_extent <= bottom - top_later
        )
        if cursor is not None and (
            unit.force_break or block_overflows or top + unit.extent > bottom + _EPS
        ):
            page += 1
            top = top_later
        for row, offset in zip(unit.rows, unit.offsets, strict=True):
            placements.append(Placement(row, page, top + offset))
        cursor = top + unit.extent
        prev = unit.rows[-1]
    return placements


def _evaluate_plan(base: Pagination, placements: list[Placement]) -> tuple[Pagination, list[Row]]:
    moved: list[Row] = []
    for pl in placements:
        r = pl.row
        moved.append(
            Row(
                pl.page,
                pl.top,
                pl.top + r.height,
                r.kind,
                pl.top + (r.baseline - r.top),
                r.text,
                r.heading,
                r.line,
                r.paragraph,
                r.index_in_paragraph,
                r.left,
                r.right,
            )
        )
    pages = max((m.page for m in moved), default=0) + 1
    sections, rules = evaluate_rows(moved, pages)
    return Pagination(
        pages, moved, sections, rules, base.frame_top, base.frame_bottom, base.page_height
    ), moved


# --- applying --------------------------------------------------------------------------------


def _page_atoms(writer: PdfWriter, index: int) -> list[pa.Atom]:
    page = writer.pages[index]
    ops = ps.parse(page.get_contents().get_data() if page.get_contents() is not None else b"")
    fonts = {
        k.lstrip("/"): ps.metrics_for(v.get_object())
        for k, v in (page["/Resources"].get("/Font") or {}).items()
    }
    return pa.split_page(ops, fonts, float(page.mediabox.height), index, float(page.mediabox.width))


def _row_atoms(
    rows: list[Row], atoms: list[pa.Atom]
) -> tuple[dict[int, list[pa.Atom]], list[pa.Atom]]:
    """Which row each drawn atom belongs to, and the shapes that belong to none.

    A shape that belongs to no line (cell shading, a table border) is harmless while its page
    stays as it is, and makes a page that has to move unmovable: it would be left behind.
    """
    owner: dict[int, list[pa.Atom]] = {id(r): [] for r in rows}
    orphans: list[pa.Atom] = []
    for atom in atoms:
        if atom.kind == "rule":
            hit = next(
                (
                    r
                    for r in rows
                    if r.kind == "rule"
                    and abs(r.top - atom.top) < 1.0
                    and abs(r.left - atom.left) < 1.5
                ),
                None,
            )
        elif atom.kind == "text":
            cands = [
                r
                for r in rows
                if r.kind == "text"
                and atom.baseline is not None
                and abs(r.baseline - atom.baseline) <= 1.6
            ]
            if not cands and atom.baseline is not None:
                cands = [
                    r for r in rows if r.kind == "text" and abs(r.baseline - atom.baseline) <= 4.0
                ]
            centre = (atom.left + atom.right) / 2
            hit = min(
                cands,
                key=lambda r: (
                    0
                    if r.left - 1 <= centre <= r.right + 1
                    else min(abs(centre - r.left), abs(centre - r.right))
                ),
                default=None,
            )
        else:
            hit = None
        if hit is None and atom.kind == "text":
            continue  # a line of blanks or spaces: nothing to see, it simply stays where it is
        if hit is None:
            orphans.append(atom)
            continue
        owner[id(hit)].append(atom)
    return owner, orphans


class _Resources:
    """Registers fonts and graphics states on destination pages for atoms that move onto them."""

    def __init__(self, writer: PdfWriter) -> None:
        self.writer = writer
        self.counter = 0

    def _dict(self, page, key: str) -> DictionaryObject:
        res = page.get("/Resources")
        res = DictionaryObject(res.get_object() if res is not None else {})
        page[NameObject("/Resources")] = res
        sub = res.get(key)
        sub = DictionaryObject(sub.get_object() if sub is not None else {})
        res[NameObject(key)] = sub
        return sub

    def mapping(
        self, source_page: int, dest_page: int, atom: pa.Atom
    ) -> dict[tuple[str, str], str]:
        out: dict[tuple[str, str], str] = {}
        if source_page == dest_page:
            return out
        src = self.writer.pages[source_page]["/Resources"]
        for key, names in (("/Font", atom.fonts), ("/ExtGState", atom.gstates)):
            if not names:
                continue
            source_dict = (src.get(key) or {}).get_object() if src.get(key) is not None else {}
            dest_page_obj = self.writer.pages[dest_page]
            dest = self._dict(dest_page_obj, key)
            for name in names:
                ref = source_dict.get("/" + name)
                if ref is None:
                    continue
                existing = next(
                    (
                        k
                        for k, v in dest.items()
                        if getattr(v, "idnum", None) == getattr(ref, "idnum", -1)
                    ),
                    None,
                )
                if existing is None:
                    self.counter += 1
                    existing = f"/CVMv{self.counter}"
                    dest[NameObject(existing)] = ref
                out[(key, name)] = existing.lstrip("/")
        return out


def _renamed(ops: list[ps.Op], mapping: dict[tuple[str, str], str]) -> list[ps.Op]:
    if not mapping:
        return ops
    out: list[ps.Op] = []
    for op in ops:
        if op.operator == "Tf" and op.operands and ("/Font", op.operands[0].value) in mapping:
            out.append(
                ps.op("Tf", ps.Name(mapping[("/Font", op.operands[0].value)]), *op.operands[1:])
            )
        elif (
            op.operator == "gs" and op.operands and ("/ExtGState", op.operands[0].value) in mapping
        ):
            out.append(ps.op("gs", ps.Name(mapping[("/ExtGState", op.operands[0].value)])))
        else:
            out.append(op)
    return out


def apply_layout(
    src: Path | str, dst: Path | str, base: Pagination, placements: list[Placement]
) -> int:
    """Write ``src`` to ``dst`` with every row moved to its placement. Returns rows moved."""
    writer = PdfWriter(clone_from=str(src))
    n_src = len(writer.pages)
    height = float(writer.pages[0].mediabox.height)
    width = float(writer.pages[0].mediabox.width)
    # A page the atom splitter cannot take apart (a table whose cells clip their text, an image)
    # may still sit in the document, provided nothing on it moves and nothing moves onto it. It is
    # left exactly as it is.
    parsed: dict[int, list[pa.Atom]] = {}
    frozen: dict[int, str] = {}
    for i in range(n_src):
        try:
            parsed[i] = _page_atoms(writer, i)
        except pa.Unsupported as exc:
            frozen[i] = str(exc)
    rows_by_page: dict[int, list[Row]] = {}
    for r in base.rows:
        rows_by_page.setdefault(r.page, []).append(r)
    owners: dict[int, dict[int, list[pa.Atom]]] = {}
    orphaned: dict[int, list[pa.Atom]] = {}
    for i, atoms in parsed.items():
        owners[i], orphaned[i] = _row_atoms(rows_by_page.get(i, []), atoms)
    placement_of: dict[int, Placement] = {id(pl.row): pl for pl in placements}
    for i, loose in orphaned.items():
        # A loose shape matters only if a row that moves sits where it is drawn.
        bands = [
            (row.top - 3.0, row.bottom + 3.0)
            for row in rows_by_page.get(i, [])
            if (pl := placement_of.get(id(row))) is not None
            and (abs(pl.dy) > 1e-6 or pl.page != i)
        ]
        stuck = next(
            (a for a in loose if any(a.top < hi and a.bottom > lo for lo, hi in bands)), None
        )
        if stuck is not None:
            raise pa.Unsupported(
                f"a {stuck.kind} at page {i + 1}, y={stuck.top:.0f}pt belongs to no line or "
                "separator, so it would be left behind by the move"
            )
    for i, why in frozen.items():
        for row in rows_by_page.get(i, []):
            pl = placement_of.get(id(row))
            if pl is not None and (abs(pl.dy) > 1e-6 or pl.page != i):
                raise pa.Unsupported(f"page {i + 1} cannot be moved ({why}) and this layout moves it")
    for pl in placements:
        if pl.page in frozen and pl.row.page != pl.page:
            raise pa.Unsupported(f"page {pl.page + 1} cannot receive content ({frozen[pl.page]})")

    pages_needed = max(pl.page for pl in placements) + 1
    while len(writer.pages) < pages_needed:
        writer.add_blank_page(width, height)
    resources = _Resources(writer)

    # Every atom of a page that gives up or receives content is re-emitted, in its original order.
    leaving: dict[int, set[int]] = {i: set() for i in range(n_src)}
    shifts: dict[int, dict[int, float]] = {i: {} for i in range(n_src)}
    appended: dict[int, list[ps.Op]] = {}
    changed: set[int] = set()
    moved = 0
    for page_index, atoms in parsed.items():
        for row_id, row_atoms in owners[page_index].items():
            pl = placement_of.get(row_id)
            if pl is None or (abs(pl.dy) < 1e-6 and pl.page == page_index):
                continue
            for atom in row_atoms:
                moved += 1
                changed.add(page_index)
                if pl.page == page_index:
                    shifts[page_index][id(atom)] = pl.dy
                else:
                    leaving[page_index].add(id(atom))
                    changed.add(pl.page)
                    mapping = resources.mapping(page_index, pl.page, atom)
                    appended.setdefault(pl.page, []).extend(
                        _renamed(pa.shifted(atom, pl.dy), mapping)
                    )

    for index in sorted(changed):
        out: list[ps.Op] = []
        if index < n_src:
            for atom in parsed[index]:
                if id(atom) in leaving[index]:
                    continue
                out.extend(pa.shifted(atom, shifts[index].get(id(atom), 0.0)))
        out.extend(appended.get(index, []))
        stream = DecodedStreamObject()
        stream.set_data(ps.join(out))
        writer.pages[index][NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    with open(dst, "wb") as handle:
        writer.write(handle)
    return moved


# --- verification ----------------------------------------------------------------------------


def verify(
    src: Path | str, dst: Path | str, placements: list[Placement], after: Pagination
) -> list[str]:
    """Check the moved file against the original: same text, every moved line identical.

    Compared on glyphs, not pixels: a line moved by a fraction of a point anti-aliases differently
    without being any different. Each line's characters must keep their text, font, size, colour
    and horizontal position, and move vertically by exactly the planned distance.
    """
    problems: list[str] = []
    before_rows = [pl.row.text for pl in placements if pl.row.kind == "text"]
    if [r.text for r in after.rows if r.kind == "text"] != before_rows:
        problems.append("the text in reading order changed")

    old, new = pdf_read.read_chars(src), pdf_read.read_chars(dst)

    def line_chars(
        pages: list[pdf_read.PageChars], page: int, baseline: float, left: float, right: float
    ):
        if page >= len(pages):
            return []
        return sorted(
            (
                c
                for c in pages[page].chars
                if abs(c.oy - baseline) <= 1.0 and left - 1 <= (c.x0 + c.x1) / 2 <= right + 1
            ),
            key=lambda c: c.x0,
        )

    bad = 0
    for pl in placements:
        row = pl.row
        if row.kind != "text":
            continue
        a = line_chars(old, row.page, row.baseline, row.left, row.right)
        shift = pl.top - row.top
        b = line_chars(new, pl.page, row.baseline + shift, row.left, row.right)
        if len(a) != len(b) or any(
            x.c != y.c
            or x.font != y.font
            or abs(x.size - y.size) > 0.01
            or x.color != y.color
            or abs(x.x0 - y.x0) > 0.05
            or abs((y.oy - x.oy) - shift) > 0.1
            for x, y in zip(a, b, strict=True)
        ):
            bad += 1
    if bad:
        problems.append(f"{bad} moved line(s) are not identical to the original")
    return problems


# --- entry point -----------------------------------------------------------------------------


def reflow_to_rules(
    src: Path | str,
    dst: Path | str,
    *,
    break_before_extra: bool = True,
    shrink: Shrink | None = None,
    force: bool = False,
) -> ReflowResult:
    """Re-flow ``src`` into ``dst`` so the pagination rules hold, or say why that cannot be done.

    ``dst`` is written only when the result is kept; the caller copies ``src`` otherwise.
    """
    before = analyse(src)
    if before.ok and not force:
        return ReflowResult(True, False, before, reason="The pagination rules already hold.")
    try:
        placements = plan_layout(before, break_before_extra=break_before_extra, shrink=shrink)
        planned, _ = _evaluate_plan(before, placements)
    except Exception as exc:  # planning is pure geometry; any failure means "leave it alone"
        return ReflowResult(False, False, before, reason=f"Could not plan a layout: {exc}")
    if not planned.ok:
        left = "; ".join(f"{r.rule}: {r.detail}" for r in planned.violations)
        return ReflowResult(
            False,
            False,
            before,
            planned,
            f"The rules cannot all be met without removing content ({left})",
        )
    try:
        moved = apply_layout(src, dst, before, placements)
    except pa.Unsupported as exc:
        return ReflowResult(
            False, False, before, reason=f"This PDF cannot be re-flowed safely: {exc}"
        )
    after = analyse(dst)
    problems = verify(src, dst, placements, after)
    if not after.ok:
        problems.append(
            "the written file does not satisfy the rules: "
            + "; ".join(r.detail for r in after.violations)
        )
    if problems:
        return ReflowResult(
            False, False, before, after, "The re-flowed file failed verification", moved, problems
        )
    return ReflowResult(
        True, True, before, after, "Re-flowed to satisfy the pagination rules.", moved
    )


__all__ = [
    "ArrayObject",
    "Placement",
    "ReflowResult",
    "apply_layout",
    "plan_layout",
    "reflow_to_rules",
    "verify",
]
