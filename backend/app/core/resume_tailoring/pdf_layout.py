"""Read a PDF CV as the page it is, so a line of text can be found again and replaced in place.

The text-line extractor next door is built for scoring and for rebuilding a document. It cannot
edit one: it joins a project title and all of its sub-bullets into one thousand-character
"bullet", and it keeps no coordinates, so nothing it returns can be located on the page. This
module reads the same PDF with PyMuPDF and keeps what an in-place edit needs:

* every character with its box, baseline, font, size and colour;
* the bullet marker split from the text it introduces (a Symbol-font dot, a Courier "o", a
  Wingdings square, or a literal glyph inside the text run);
* bullets and prose grouped into the paragraphs a reader sees, hanging indent and all.

The result is an ordinary :class:`ResumeDocument` (so the planner, validator and scorer are
untouched) whose editable lines each carry the geometry of the paragraph they came from.
"""
# ruff: noqa: RUF001
# Marker glyphs include typographic dashes and bullets.

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.resume_tailoring.extract import (
    _SUMMARY_HEADING,
    _split_header,
    _stitch,
    is_heading,
    parse_styled_lines,
)
from app.core.resume_tailoring.model import LineKind, ResumeDocument, Style
from app.core.resume_tailoring.pdf_read import PChar, read_chars

#: Ligature glyphs, expanded to the letters they stand for. A PDF that sets "fl" as one glyph
#: extracts as "Airﬂow", which no keyword match, planner prompt or ATS tokenizer will recognise
#: as "Airflow" — and the planner writes the plain letters back.
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
#: Glyphs that introduce a list item when they stand alone at the start of a line.
MARKER_GLYPHS = frozenset("•●▪■□◦‣⁃·∙➢➤►➔–—-*")
#: Non-last lines whose right edges agree within this are justified text.
_JUSTIFY_SPREAD = 1.5
#: Keep text this far inside the page edge whatever the column estimate says.
_PAGE_EDGE = 14.0
#: Characters whose baselines differ by no more than this sit on one line.
_BASELINE_TOL = 1.6
#: A horizontal gap wider than this many font sizes separates two columns of one row.
_COLUMN_GAP = 2.0
#: Tolerance, in points, when deciding two lines share a left edge.
_X_TOL = 2.5
#: Largest vertical gap between a line and the previous one that still counts as the same
#: paragraph. Normal leading leaves roughly zero; paragraph spacing is several points.
_MAX_LINE_GAP = 3.0
#: Furthest right of a bullet's first-line text that its wrapped lines may sit (hanging indent).
_HANGING_MAX = 6.0
#: A bullet whose next bullet is indented by more than this is a sub-heading, not an item.
_NEST_INDENT = 4.0


@dataclass
class PLine:
    """One physical line: its characters, with the leading marker (if any) set apart."""

    page: int
    chars: list[PChar]
    bbox: tuple[float, float, float, float]
    marker_n: int = 0

    @property
    def body(self) -> list[PChar]:
        return self.chars[self.marker_n :]

    @property
    def marker(self) -> str:
        return "".join(ch.c for ch in self.chars[: self.marker_n]).strip()

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(ch.c for ch in self.body)).strip()

    def _ink(self, chars: list[PChar]) -> list[PChar]:
        return [ch for ch in chars if not ch.is_space]

    @property
    def body_x0(self) -> float:
        ink = self._ink(self.body)
        return min((ch.x0 for ch in ink), default=self.bbox[0])

    @property
    def body_x1(self) -> float:
        ink = self._ink(self.body)
        return max((ch.x1 for ch in ink), default=self.bbox[2])

    @property
    def marker_x0(self) -> float:
        ink = self._ink(self.chars[: self.marker_n])
        return min((ch.x0 for ch in ink), default=self.bbox[0])

    @property
    def baseline(self) -> float:
        ys = sorted(ch.oy for ch in self._ink(self.body))
        return ys[len(ys) // 2] if ys else self.bbox[3]

    @property
    def size(self) -> float:
        sizes = [ch.size for ch in self._ink(self.body)]
        return max(set(sizes), key=sizes.count) if sizes else 0.0


@dataclass
class PParagraph:
    """A bullet or a block of prose, as the lines that make it up on the page."""

    lines: list[PLine] = field(default_factory=list)
    kind: str = "plain"  # "bullet" | "plain"

    @property
    def page(self) -> int:
        return self.lines[0].page

    @property
    def marker(self) -> str:
        return self.lines[0].marker if self.kind == "bullet" else ""

    @property
    def text(self) -> str:
        out = ""
        for line in self.lines:
            out = _stitch(out, line.text) if out else line.text
        return out

    @property
    def text_x(self) -> float:
        return self.lines[0].body_x0

    @property
    def cont_x(self) -> float:
        return self.lines[1].body_x0 if len(self.lines) > 1 else self.text_x

    @property
    def marker_x(self) -> float:
        return self.lines[0].marker_x0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            min(ln.bbox[0] for ln in self.lines),
            min(ln.bbox[1] for ln in self.lines),
            max(ln.bbox[2] for ln in self.lines),
            max(ln.bbox[3] for ln in self.lines),
        )


# --- reading ------------------------------------------------------------------------------


def _marker_length(chars: list[PChar]) -> int:
    """How many leading characters are a list marker plus the gap after it (0 if none)."""
    i = 0
    while i < len(chars) and chars[i].is_space:
        i += 1
    if i >= len(chars):
        return 0
    first = chars[i]
    glyph = first.c[0]
    # Beyond the listed glyphs, any "symbol, other/modifier" character (○ ◆ ➜ ✓ …) set apart by
    # a gap is a bullet: CVs use whatever their template's list style draws.
    is_marker = (
        glyph in MARKER_GLYPHS
        or ord(glyph) >= 0xE000
        or unicodedata.category(glyph) in ("So", "Sk")
    )
    j = i + 1
    if not is_marker and glyph == "o":
        # A sub-bullet "o" is set in another face or size from the text after it; the word "o"
        # alone at the start of a line essentially never occurs otherwise.
        k = j
        while k < len(chars) and chars[k].is_space:
            k += 1
        is_marker = (
            k < len(chars)
            and k > j
            and (chars[k].font != first.font or chars[k].size != first.size)
        )
    if not is_marker:
        return 0
    k = j
    while k < len(chars) and chars[k].is_space:
        k += 1
    # A marker has to be followed by a gap and then something: "-5%" and "*" alone are not.
    return k if k > j and k < len(chars) else 0


def read_lines(path: str) -> tuple[list[PLine], list[tuple[float, float]]]:
    """Every non-blank line of the PDF in reading order, plus each page's size.

    Lines are rebuilt from the characters' own positions rather than taken from content-stream
    order. A file whose text was replaced in place (new glyphs appended after the old marker
    glyphs) would otherwise read back as a bare bullet on one line and its text on the next.
    Positions are the same in either file.
    """
    lines: list[PLine] = []
    sizes: list[tuple[float, float]] = []
    for pno, page in enumerate(read_chars(path)):
        sizes.append((page.width, page.height))
        chars = [
            PChar(
                _LIGATURES.get(ch.c, ch.c),
                ch.x0,
                ch.y0,
                ch.x1,
                ch.y1,
                ch.oy,
                ch.font,
                ch.size,
                ch.color,
                ch.flags,
            )
            for ch in page.chars
        ]
        lines.extend(_segment(pno, chars))
    return lines, sizes


def _segment(pno: int, chars: list[PChar]) -> list[PLine]:
    """Group one page's characters into lines by baseline, splitting wide horizontal gaps."""
    ordered = sorted(chars, key=lambda c: (c.oy, c.x0))
    rows: list[list[PChar]] = []
    for ch in ordered:
        if rows and abs(ch.oy - rows[-1][0].oy) <= _BASELINE_TOL:
            rows[-1].append(ch)
        else:
            rows.append([ch])
    out: list[PLine] = []
    for row in rows:
        row.sort(key=lambda c: c.x0)
        segment: list[PChar] = [row[0]]
        for prev, ch in zip(row, row[1:], strict=False):
            if ch.x0 - prev.x1 > _COLUMN_GAP * max(prev.size, ch.size):
                out.append(_line(pno, segment))
                segment = []
            segment.append(ch)
        out.append(_line(pno, segment))
    out = [ln for ln in out if any(not c.is_space for c in ln.chars)]
    for ln in out:
        ln.marker_n = _marker_length(ln.chars)
    return _reading_order(out)


def _line(pno: int, chars: list[PChar]) -> PLine:
    box = (
        min(c.x0 for c in chars),
        min(c.y0 for c in chars),
        max(c.x1 for c in chars),
        max(c.y1 for c in chars),
    )
    return PLine(pno, chars, box)


def _reading_order(page_lines: list[PLine]) -> list[PLine]:
    """Top-to-bottom, and left-to-right among lines that share a row."""
    ordered = sorted(page_lines, key=lambda ln: (ln.bbox[1], ln.bbox[0]))
    out: list[PLine] = []
    row: list[PLine] = []
    for line in ordered:
        if row and abs(line.bbox[1] - row[0].bbox[1]) > 2.0:
            out.extend(sorted(row, key=lambda ln: ln.bbox[0]))
            row = []
        row.append(line)
    out.extend(sorted(row, key=lambda ln: ln.bbox[0]))
    return out


# --- grouping -----------------------------------------------------------------------------


def _continues(prev: PParagraph, line: PLine, *, summary: bool) -> bool:
    """Whether ``line`` is the next line of the paragraph ``prev``."""
    last = prev.lines[-1]
    if line.page != last.page or line.marker_n:
        return False
    if abs(line.size - last.size) > 0.6 or line.bbox[1] - last.bbox[3] > _MAX_LINE_GAP:
        return False
    if prev.kind == "bullet":
        if len(prev.lines) == 1:
            # Word sets the wrapped lines of a bullet on the hanging indent, which sits a few
            # points right of where the first line's text happened to start after its marker.
            return prev.text_x - _X_TOL <= line.body_x0 <= prev.text_x + _HANGING_MAX
        return abs(line.body_x0 - prev.cont_x) <= _X_TOL
    return summary and abs(line.body_x0 - prev.text_x) <= _X_TOL


def _summary_flags(lines: list[PLine], header_len: int) -> list[bool]:
    """Which lines sit in a summary-like block, where plain lines form one paragraph.

    Everywhere else a plain line is a label, an employer or a date line — one line, one unit —
    and joining neighbours would fuse "SimplyPhi, Woking" with the role line beneath it.
    """
    flags: list[bool] = []
    in_summary = True  # the unlabelled block that follows the contact details
    for index, line in enumerate(lines):
        if index < header_len:
            flags.append(False)
            continue
        text = line.text
        if is_heading(text):
            in_summary = bool(_SUMMARY_HEADING.search(text))
            flags.append(False)
            continue
        flags.append(in_summary)
    return flags


def group_paragraphs(lines: list[PLine]) -> list[PParagraph]:
    header_len = _split_header([ln.text for ln in lines])
    summary = _summary_flags(lines, header_len)
    paragraphs: list[PParagraph] = []
    for line, in_summary in zip(lines, summary, strict=True):
        if paragraphs and _continues(paragraphs[-1], line, summary=in_summary):
            paragraphs[-1].lines.append(line)
        else:
            paragraphs.append(PParagraph([line], "bullet" if line.marker_n else "plain"))
    return paragraphs


def right_limit(par: PParagraph, siblings: list[PParagraph], page_width: float) -> float:
    """Where the column ends: the furthest any wrapped sibling line reaches."""
    edges = [ln.body_x1 for ln in par.lines]
    if par.kind == "plain" and len(par.lines) == 1:
        # A one-line row of a table (a skills row) has no wrapped lines to show where its column
        # ends. The longest sibling row in the same column does.
        for other in siblings:
            if (
                other.page == par.page
                and other.kind == "plain"
                and len(other.lines) == 1
                and abs(other.text_x - par.text_x) <= _X_TOL
            ):
                edges.append(other.lines[0].body_x1)
    for other in siblings:
        if (
            other.page == par.page
            and other.kind == par.kind
            and abs(other.cont_x - par.cont_x) <= 4.0
        ):
            edges.extend(ln.body_x1 for ln in other.lines[:-1])
    return min(max(edges), page_width - _PAGE_EDGE)


def is_justified(par: PParagraph) -> tuple[bool, float]:
    if len(par.lines) < 2:
        return False, 0.0
    edges = [ln.body_x1 for ln in par.lines[:-1]]
    return (max(edges) - min(edges) <= _JUSTIFY_SPREAD), max(edges)


def capacity_chars(par: PParagraph, siblings: list[PParagraph], page_width: float) -> int:
    """About how many characters this paragraph can hold without needing another line.

    The paragraph's own length plus the unused width at the end of its last line, less a safety
    margin. It is a hint to the planner, not the test: the real fit check lays the words out.
    """
    last = par.lines[-1]
    right = right_limit(par, siblings, page_width)
    chars = [c for c in last.body if not c.is_space]
    if not chars:
        return len(par.text)
    width = max(1.0, last.body_x1 - last.body_x0)
    free = max(0.0, right - last.body_x1)
    return len(par.text) + int((free / (width / len(chars))) * 0.85)


# --- document -----------------------------------------------------------------------------


def _colour(color: int) -> tuple[int, int, int] | None:
    rgb = ((color >> 16) & 255, (color >> 8) & 255, color & 255)
    return None if rgb == (0, 0, 0) else rgb


def _style_of(par: PParagraph) -> Style:
    first = next((ch for ch in par.lines[0].body if not ch.is_space), None)
    if first is None:
        return Style()
    name = re.sub(r"^[A-Z]{6}\+", "", first.font)
    return Style(
        font=name,
        size=round(first.size, 1),
        bold="bold" in name.lower(),
        italic="italic" in name.lower(),
        colour=_colour(first.color),
    )


def build_document(path: str) -> ResumeDocument:
    """Parse a PDF CV into a :class:`ResumeDocument` that remembers where each line sits."""
    lines, sizes = read_lines(path)
    paragraphs = group_paragraphs(lines)
    pairs = [(("• " + p.text) if p.kind == "bullet" else p.text, _style_of(p)) for p in paragraphs]
    doc = parse_styled_lines(pairs, source_format="pdf", joined=True)
    if not paragraphs:
        return doc

    raws = [raw for raw, _ in pairs]
    header_len = _split_header(raws)
    body_pars = [
        p
        for p, raw in zip(paragraphs[header_len:], raws[header_len:], strict=True)
        if not is_heading(raw)
    ]
    placed = list(zip(doc.header, paragraphs[:header_len], strict=True))
    section_lines = [ln for section in doc.sections for ln in section.lines]
    placed += list(zip(section_lines, body_pars, strict=True))

    layout = {line.id: par for line, par in placed}
    doc.layout = layout
    doc.capacity = {
        line_id: capacity_chars(par, paragraphs, sizes[par.page][0])
        for line_id, par in layout.items()
    }
    _demote_sub_headings(doc)
    _mark_skill_rows(doc)

    width, height = sizes[0] if sizes else (0.0, 0.0)
    chars = [ch for ln in lines for ch in ln.chars if not ch.is_space]
    if chars and width:
        doc.page_margins = (
            round(min(c.x0 for c in chars), 1),
            round(max(0.0, width - max(c.x1 for c in chars)), 1),
            round(min(c.y0 for c in chars), 1),
            round(max(0.0, height - max(c.y1 for c in chars)), 1),
        )
    return doc


def _demote_sub_headings(doc: ResumeDocument) -> None:
    """A bullet that introduces more-indented bullets is a project heading, so it is fixed.

    "• IRIS 2.0 – AI Property Asset Intelligence Platform" followed by "o Led the transformation…"
    is a title with its own bullets. Editing the title would rename a project, which is exactly
    the kind of fact a tailored CV must never change.
    """
    for section in doc.sections:
        for line, nxt in zip(section.lines, section.lines[1:], strict=False):
            a, b = doc.layout.get(line.id), doc.layout.get(nxt.id)
            if (
                line.kind is LineKind.BULLET
                and a
                and b
                and b.kind == "bullet"
                and b.page == a.page
                and (b.marker != a.marker or b.marker_x > a.marker_x + _NEST_INDENT)
            ):
                line.kind = LineKind.FIXED


_SKILLS_HEADING = re.compile(r"skill|highlight|technolog|competenc|expertise|tool|stack", re.I)
_SKILL_ROW = re.compile(r"^[A-Za-z][A-Za-z0-9 &/+.\-]{1,40}:\s+\S")


def _mark_skill_rows(doc: ResumeDocument) -> None:
    """Make "Label: item, item" rows (one or two lines) of a skills table editable (append-only).

    Only rows that stand alone are marked: a row whose text is cut mid-phrase and carried on by
    the next line of the table (an unclosed bracket, a continuation that starts in lower case)
    stays fixed, because adding to half a sentence would corrupt the other half.
    """
    for section in doc.sections:
        if not _SKILLS_HEADING.search(section.heading or ""):
            continue
        for line, nxt in zip(section.lines, [*section.lines[1:], None], strict=True):
            par = doc.layout.get(line.id)
            if (
                line.kind is not LineKind.FIXED
                or par is None
                or len(par.lines) > 2  # type: ignore[attr-defined]
                or not _SKILL_ROW.match(line.text)
                or line.text.count("(") != line.text.count(")")
                or line.text.rstrip().endswith((",", "&", "and", "-"))
            ):
                continue
            if nxt is not None and nxt.text[:1].islower():
                continue
            line.kind = LineKind.SKILL
