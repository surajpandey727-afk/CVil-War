"""Replace the text of chosen paragraphs inside the candidate's own PDF.

The file that gets submitted has to be the candidate's CV, not a new document that resembles it.
So nothing is rebuilt. For each edited paragraph the old glyphs are removed from the page's
content stream (so the old words are gone from text extraction too, not just hidden under a
white box) and the new words are drawn on the original baselines, in the original fonts, sizes
and colours, from the original left edge. Rules, tables, images, margins,
other paragraphs and the page itself are not touched.

The layout rules are deliberately conservative, because the failure mode that matters is a
quietly damaged page:

* the new text must fit on the lines the old text occupied, inside the same column — if it
  would need another line, or reach past the column, the edit is skipped and reported rather
  than pushing the content below it around;
* a paragraph that was justified stays justified, and a ragged one stays ragged;
* styling follows the words: an unchanged bold lead-in stays bold, inserted words take the
  style of the word they sit beside.
"""

from __future__ import annotations

import difflib
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from app.core.resume_tailoring import pdf_stream as ps
from app.core.resume_tailoring.model import ResumeDocument
from app.core.resume_tailoring.pdf_fonts import FontChoice, FontResolver, bare_name
from app.core.resume_tailoring.pdf_layout import (
    PChar,
    PLine,
    PParagraph,
    is_justified,
    right_limit,
)
from app.core.resume_tailoring.pdf_read import SYNTHETIC
from app.core.resume_tailoring.pdf_write import FontRegistry, run_ops

#: Slack, in points, when judging whether a line reaches the column edge.
_FIT_TOLERANCE = 0.3
#: How far a justified line may squeeze its spaces to take one more word, as Word does.
_JUSTIFY_SHRINK = 0.8
#: How far a glyph's baseline may sit from the line's and still be part of that line, in points.
_BASELINE_MATCH = 1.5


@dataclass(frozen=True)
class WordStyle:
    font: str
    size: float
    color: int


@dataclass
class Word:
    text: str
    style: WordStyle


@dataclass
class Run:
    """One piece of text drawn at one position in one font."""

    x: float
    y: float
    text: str
    choice: FontChoice
    size: float
    color: int


@dataclass
class EditOutcome:
    line_id: str
    status: str  # "applied" | "skipped"
    reason: str = ""
    page: int = -1
    #: Union of the old and new ink, in page points, for visual comparison and audit.
    rect: tuple[float, float, float, float] | None = None
    substituted_fonts: list[str] = field(default_factory=list)
    #: Lines the paragraph occupied before and after the edit (applied edits only).
    old_lines: int = 0
    new_lines: int = 0
    #: How far up the last line moved because the paragraph got shorter, in points.
    shrink: float = 0.0
    #: The paragraph was removed altogether (a suppressed bullet); ``new_lines`` is then 0.
    removed: bool = False


@dataclass
class PdfEditResult:
    path: Path
    outcomes: list[EditOutcome]

    @property
    def applied(self) -> list[EditOutcome]:
        return [o for o in self.outcomes if o.status == "applied"]

    @property
    def skipped(self) -> list[EditOutcome]:
        return [o for o in self.outcomes if o.status == "skipped"]


# --- reading the old paragraph -------------------------------------------------------------


def _style_of(ch: PChar) -> WordStyle:
    return WordStyle(bare_name(ch.font), round(ch.size, 2), ch.color)


def old_words(par: PParagraph) -> list[Word]:
    """The paragraph's words with the style each was set in.

    A word broken across two lines at a hyphen ("Azure-" / "based") is one word, which is how
    it appears in the extracted text the planner edited.
    """
    words: list[Word] = []
    carry: Word | None = None
    for line in par.lines:
        current: list[PChar] = []

        def flush() -> None:
            nonlocal carry
            if not current:
                return
            text = "".join(c.c for c in current)
            style = _style_of(current[0])
            if carry is not None:
                carry.text += text
                words.append(carry)
                carry = None
            else:
                words.append(Word(text, style))
            current.clear()

        for ch in line.body:
            if ch.is_space:
                flush()
            else:
                current.append(ch)
        if current and current[-1].c == "-" and line is not par.lines[-1]:
            carry = Word("".join(c.c for c in current), _style_of(current[0]))
            current.clear()
        else:
            flush()
    return words


def _line_words(line: PLine) -> list[Word]:
    """The words on one physical line, with no joining across the line break."""
    words: list[Word] = []
    current: list[PChar] = []
    for ch in [*line.body, None]:
        if ch is not None and not ch.is_space:
            current.append(ch)
        elif current:
            words.append(Word("".join(c.c for c in current), _style_of(current[0])))
            current = []
    return words


def _styled_new_words(old: list[Word], new_text: str) -> list[Word]:
    """Give each new word the style of the old word it replaces or sits beside."""
    new = new_text.split()
    matcher = difflib.SequenceMatcher(a=[w.text for w in old], b=new, autojunk=False)
    out: list[Word | None] = [None] * len(new)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        for offset, j in enumerate(range(j1, j2)):
            if tag == "equal":
                out[j] = old[i1 + offset]
            elif tag == "replace":
                out[j] = Word(new[j], old[min(i1 + offset, i2 - 1)].style)
            elif tag == "insert":
                out[j] = Word(new[j], old[max(i1 - 1, 0)].style)
    return [w for w in out if w is not None]


# --- geometry -------------------------------------------------------------------------------


def _line_span(line: PLine) -> tuple[float, float, float]:
    """The baseline, left and right bounds of a line's body text (the marker is left alone).

    The left bound must not reach back into the gap after the bullet marker: that gap is a real
    space glyph, and losing it leaves "oLed the transformation" in the text layer while the
    page still looks perfect. The space after a marker can be wider than the gap to the text,
    so its right edge, not the first body glyph's left edge, is the boundary.
    """
    left = (
        max(c.x1 for c in line.chars[: line.marker_n]) + 0.05
        if line.marker_n
        else line.bbox[0] - 0.3
    )
    # Trailing spaces count: a line's last space is a glyph too, and left behind it would land in
    # the middle of the longer text that replaces the line.
    return line.baseline, left, line.bbox[2] + 0.3


# --- laying the new paragraph out ---------------------------------------------------------


class _Measure:
    def __init__(self, resolver: FontResolver) -> None:
        self.resolver = resolver
        #: Ratio of how wide the source actually set its text to how wide the font says it is.
        #: Word's layout sits a fraction of a percent tighter than nominal advances, which is
        #: enough to push an unchanged paragraph onto an extra line if ignored.
        self.scale = 1.0

    def segments(self, word: Word) -> list[tuple[str, FontChoice]] | str:
        return self.resolver.segments(word.style.font, word.text)

    def width(self, word: Word) -> float:
        segs = self.segments(word)
        if isinstance(segs, str):
            return 0.0
        return sum(c.font.text_length(t, fontsize=word.style.size) for t, c in segs) * self.scale

    def space(self, word: Word) -> float:
        font = self.resolver.space(word.style.font).font
        w = font.text_length(" ", fontsize=word.style.size)
        return (w if w >= word.style.size * 0.1 else word.style.size * 0.25) * self.scale

    def calibrate(self, par: PParagraph) -> None:
        """Measure how the source set this paragraph against what the fonts predict."""
        self.scale = 1.0
        ratios: list[float] = []
        justified = is_justified(par)[0]
        for index, line in enumerate(par.lines):
            if justified and index < len(par.lines) - 1:
                continue  # spaces were stretched; only the widths of ragged lines say anything
            chunk = _line_words(line)
            if not chunk:
                continue
            nominal = sum(self.width(w) for w in chunk) + sum(self.space(w) for w in chunk[:-1])
            if nominal > 0:
                ratios.append((line.body_x1 - line.body_x0) / nominal)
        if ratios:
            self.scale = min(1.03, max(0.97, statistics.median(ratios)))


def _wrap(
    words: list[Word], widths: list[float], limits: list[float], measure: _Measure, shrink: float
) -> list[list[int]] | str:
    """Greedy line breaking. Returns word-index lines, or the reason it cannot fit."""
    lines: list[list[int]] = [[]]
    used = 0.0
    for index, word in enumerate(words):
        row = len(lines) - 1
        cap = limits[min(row, len(limits) - 1)]
        gap = measure.space(words[lines[-1][-1]]) * shrink if lines[-1] else 0.0
        if lines[-1] and used + gap + widths[index] > cap + _FIT_TOLERANCE:
            lines.append([])
            used = 0.0
            row += 1
            gap = 0.0
            cap = limits[min(row, len(limits) - 1)]
        if widths[index] > cap + _FIT_TOLERANCE:
            return f"the word '{word.text}' is wider than the column"
        lines[-1].append(index)
        used += gap + widths[index]
    return lines


def plan_paragraph(
    par: PParagraph,
    new_text: str,
    siblings: list[PParagraph],
    resolver: FontResolver,
    page_width: float,
) -> tuple[list[Run], tuple[float, float, float, float], list[str]] | str:
    """Lay ``new_text`` out in the space ``par`` occupied. Returns runs, or the reason not to."""
    old = old_words(par)
    if not old:
        return "the original paragraph has no text to take styling from"
    words = _styled_new_words(old, new_text)
    if not words:
        return "the replacement text is empty"

    measure = _Measure(resolver)
    measure.calibrate(par)
    for word in words:
        segs = measure.segments(word)
        if isinstance(segs, str):
            return segs

    right = right_limit(par, siblings, page_width)
    justified, edge = is_justified(par)
    if justified:
        right = edge
    x_first, x_cont = par.text_x, par.cont_x
    limits = [right - x_first] + [right - x_cont]
    widths = [measure.width(w) for w in words]
    wrapped = _wrap(words, widths, limits, measure, _JUSTIFY_SHRINK if justified else 1.0)
    if isinstance(wrapped, str):
        return wrapped
    if len(wrapped) > len(par.lines):
        return f"the edit needs {len(wrapped)} lines but the original has {len(par.lines)}"

    runs: list[Run] = []
    substituted: list[str] = []
    for row, indices in enumerate(wrapped):
        line = par.lines[row]
        x = x_first if row == 0 else x_cont
        last = row == len(wrapped) - 1
        stretch = 0.0
        if justified and not last and len(indices) > 1:
            natural = sum(widths[i] for i in indices) + sum(
                measure.space(words[i]) for i in indices[:-1]
            )
            stretch = (right - x - natural) / (len(indices) - 1)
        for pos, i in enumerate(indices):
            word = words[i]
            seg_x = x
            for text, choice in measure.segments(word):  # type: ignore[union-attr]
                if choice.source != "embedded":
                    substituted.append(f"{word.style.font}->{choice.name}")
                runs.append(
                    Run(seg_x, line.baseline, text, choice, word.style.size, word.style.color)
                )
                seg_x += choice.font.text_length(text, fontsize=word.style.size) * measure.scale
            x += widths[i]
            if pos < len(indices) - 1:
                runs.append(
                    Run(
                        x,
                        line.baseline,
                        " ",
                        resolver.space(word.style.font),
                        word.style.size,
                        word.style.color,
                    )
                )
                x += measure.space(word) + stretch

    ink = [
        (
            r.x,
            r.y - r.size,
            r.x + r.choice.font.text_length(r.text, fontsize=r.size),
            r.y + r.size * 0.25,
        )
        for r in runs
    ]
    old_box = par.bbox
    rect = (
        min(old_box[0], min(b[0] for b in ink)),
        min(old_box[1], min(b[1] for b in ink)),
        max(old_box[2], max(b[2] for b in ink)),
        max(old_box[3], max(b[3] for b in ink)),
    )
    return runs, rect, sorted(set(substituted))


# --- editing --------------------------------------------------------------------------------


@dataclass
class _Planned:
    line_id: str
    par: PParagraph
    runs: list[Run]
    rect: tuple[float, float, float, float]
    substituted: list[str]
    #: Remove the paragraph instead of rewriting it.
    delete: bool = False


def _page_fonts(page: Any) -> dict[str, ps.FontMetrics]:
    fonts = (page.get("/Resources") or {}).get("/Font") or {}
    return {
        key.lstrip("/"): ps.metrics_for(ref.get_object()) for key, ref in fonts.get_object().items()
    }


def _supported(page: Any) -> str | None:
    """Why this page cannot be edited in place, or None.

    Rotated and offset pages are refused rather than risk text landing in the wrong place.
    """
    box = [float(v) for v in page.mediabox]
    if int(page.get("/Rotate", 0) or 0) % 360:
        return "the page is rotated"
    crop = page.get("/CropBox")
    offset = abs(box[0]) > 0.01 or abs(box[1]) > 0.01
    if offset or (
        crop is not None and [round(float(v), 2) for v in crop] != [round(v, 2) for v in box]
    ):
        return "the page has an offset or cropped box"
    return None


def _edit_page(
    writer: PdfWriter,
    index: int,
    items: list[_Planned],
    fonts: FontRegistry,
    outcomes: list[EditOutcome],
) -> None:
    """Remove the old glyphs of every planned paragraph on one page and draw the new text."""
    page = writer.pages[index]
    height = float(page.mediabox.height)
    contents = page.get_contents()
    ops = ps.parse(contents.get_data() if contents is not None else b"")
    interp = ps.Interpreter(ops, _page_fonts(page))

    doomed: set[int] = set()
    inserts: dict[int, list[ps.Op]] = {}
    accepted: list[_Planned] = []
    for item in items:
        mine: set[int] = set()
        for line in item.par.lines:
            baseline, left, right = _line_span(line)
            if item.delete:  # a removed bullet takes its marker with it
                left = line.bbox[0] - 0.3
            for gi, g in enumerate(interp.glyphs):
                if (
                    abs((height - g.y) - baseline) <= _BASELINE_MATCH
                    and left <= (g.x0 + g.x1) / 2 <= right
                ):
                    mine.add(gi)
        expected = sum(
            1
            for ln in item.par.lines
            for c in (ln.chars if item.delete else ln.body)
            if not c.flags & SYNTHETIC
        )
        if not mine or abs(len(mine) - expected) > max(1, expected // 20):
            why = (
                "the old text could not be located in the page content "
                f"({len(mine)} of {expected} glyphs)"
            )
            outcomes.append(EditOutcome(item.line_id, "skipped", why, page=index))
            continue
        end = interp.block_end(min(interp.glyphs[gi].op for gi in mine))
        if end is None:
            outcomes.append(
                EditOutcome(
                    item.line_id,
                    "skipped",
                    "the old text is not in a plain text object",
                    page=index,
                )
            )
            continue
        runs = [] if item.delete else run_ops(item.runs, interp.ctm_after[end], height, index, fonts)
        if not runs and not item.delete:
            outcomes.append(
                EditOutcome(
                    item.line_id, "skipped", "the page transform cannot be inverted", page=index
                )
            )
            continue
        doomed |= mine
        inserts.setdefault(end, []).extend(runs)
        accepted.append(item)

    if not accepted:
        return
    rewritten = ps.remove_glyphs(ops, interp, doomed)
    final: list[ps.Op] = []
    for i, new_op in enumerate(rewritten):
        if new_op is not None:
            final.append(new_op)
        final.extend(inserts.get(i, []))
    stream = DecodedStreamObject()
    stream.set_data(ps.join(final))
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    for item in accepted:
        lines = item.par.lines
        if item.delete:
            outcomes.append(
                EditOutcome(
                    item.line_id,
                    "applied",
                    page=index,
                    rect=item.rect,
                    old_lines=len(lines),
                    new_lines=0,
                    removed=True,
                )
            )
            continue
        new_lines = max(1, min(len(lines), len({round(r.y, 1) for r in item.runs})))
        outcomes.append(
            EditOutcome(
                item.line_id,
                "applied",
                page=index,
                rect=item.rect,
                substituted_fonts=item.substituted,
                old_lines=len(lines),
                new_lines=new_lines,
                shrink=max(0.0, lines[-1].baseline - lines[new_lines - 1].baseline),
            )
        )


def edit_pdf_in_place(
    src: Path | str, original: ResumeDocument, edits: dict[str, str], out: Path | str
) -> PdfEditResult:
    """Write ``edits`` (line id -> new text) into a copy of ``src`` saved at ``out``."""
    out = Path(out)
    writer = PdfWriter(clone_from=str(src))
    outcomes: list[EditOutcome] = []
    resolver = FontResolver(writer)
    fonts = FontRegistry(writer)
    paragraphs = [p for p in original.layout.values() if isinstance(p, PParagraph)]
    planned: dict[int, list[_Planned]] = {}

    for line_id, new_text in edits.items():
        par = original.layout.get(line_id)
        line = original.bullet_by_id(line_id)
        if not isinstance(par, PParagraph) or line is None:
            outcomes.append(EditOutcome(line_id, "skipped", "the line has no position in the PDF"))
            continue
        if par.page >= len(writer.pages):
            outcomes.append(
                EditOutcome(line_id, "skipped", "the line is on a page the file does not have")
            )
            continue
        why = _supported(writer.pages[par.page])
        if why:
            outcomes.append(EditOutcome(line_id, "skipped", why, page=par.page))
            continue
        if not new_text.strip():  # an empty replacement removes the paragraph
            planned.setdefault(par.page, []).append(
                _Planned(line_id, par, [], par.bbox, [], delete=True)
            )
            continue
        plan = plan_paragraph(
            par, new_text, paragraphs, resolver, float(writer.pages[par.page].mediabox.width)
        )
        if isinstance(plan, str):
            outcomes.append(EditOutcome(line_id, "skipped", plan, page=par.page))
            continue
        runs, rect, substituted = plan
        planned.setdefault(par.page, []).append(_Planned(line_id, par, runs, rect, substituted))

    for index, items in sorted(planned.items()):
        _edit_page(writer, index, items, fonts, outcomes)
    fonts.finalize()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as handle:
        writer.write(handle)
    return PdfEditResult(out, outcomes)


def column_gap(par: PParagraph) -> float:
    """Median inter-word gap of the original paragraph (used by tests to check spacing)."""
    gaps: list[float] = []
    for line in par.lines:
        ink = [c for c in line.body if not c.is_space]
        gaps += [b.x0 - a.x1 for a, b in zip(ink, ink[1:], strict=False) if b.x0 - a.x1 > 0.5]
    return statistics.median(gaps) if gaps else 0.0
