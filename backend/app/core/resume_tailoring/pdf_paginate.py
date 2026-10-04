"""Where a PDF's sections fall on its pages, judged against the owner's pagination rules.

The rules are hard requirements, not preferences:

1. Education & Qualifications and Work & Leadership Experience start and end on the same page.
2. Extra-Curricular Experience starts on a new page.
3. The first horizontal separator is on page 1.
4. Nothing is orphaned: no heading stranded at the foot of a page, no separator left alone at the
   top or bottom, no lone line of a paragraph pushed across a break.
5. No page is blank.

:func:`analyse` measures a file against them and says exactly what it found, so every generation
reports the result rule by rule instead of leaving "looks fine" to a glance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.resume_tailoring import pdf_read
from app.core.resume_tailoring.extract import is_heading
from app.core.resume_tailoring.pdf_layout import PLine, PParagraph, group_paragraphs, read_lines

_EDUCATION = re.compile(r"educat|qualification|academic", re.I)
_EXTRA = re.compile(r"extra[- ]?curricular|volunteer", re.I)
_WORK = re.compile(r"work|experience|employment|career|leadership", re.I)
#: A heading may be followed by this many body lines on its own page before it counts as orphaned.
_MIN_LINES_AFTER_HEADING = 2
#: A rule closer than this to the heading it belongs to is that heading's separator.
_RULE_REACH = 18.0


#: A rule this share of the text width or more is a section separator; narrower ones are table
#: borders or underlines and belong to what they sit beside.
SEPARATOR_SHARE = 0.85


def is_separator(row: Row, text_width: float) -> bool:
    return row.kind == "rule" and (row.right - row.left) >= SEPARATOR_SHARE * text_width


def section_role(heading: str) -> str:
    """ "education", "extra", "work" or "other" for a heading's text."""
    if _EXTRA.search(heading):
        return "extra"
    if _EDUCATION.search(heading):
        return "education"
    if _WORK.search(heading):
        return "work"
    return "other"


@dataclass
class Row:
    """One physical line of the page, or one rule, in reading order."""

    page: int
    top: float
    bottom: float
    kind: str  # "text" | "rule"
    baseline: float = 0.0
    text: str = ""
    heading: bool = False
    line: PLine | None = field(default=None, repr=False)
    paragraph: PParagraph | None = field(default=None, repr=False)
    index_in_paragraph: int = 0
    left: float = 0.0
    right: float = 0.0

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass
class Section:
    heading: str
    role: str
    rows: list[Row]

    @property
    def pages(self) -> set[int]:
        return {r.page for r in self.rows if r.kind == "text"}


@dataclass
class RuleResult:
    rule: str
    ok: bool
    applicable: bool = True
    detail: str = ""


@dataclass
class Pagination:
    pages: int
    rows: list[Row]
    sections: list[Section]
    rules: list[RuleResult]
    frame_top: float
    frame_bottom: float
    page_height: float

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.rules)

    @property
    def violations(self) -> list[RuleResult]:
        return [r for r in self.rules if not r.ok]

    def to_dict(self) -> dict[str, object]:
        return {
            "pages": self.pages,
            "ok": self.ok,
            "rules": [
                {"rule": r.rule, "ok": r.ok, "applicable": r.applicable, "detail": r.detail}
                for r in self.rules
            ],
            "sections": [
                {"heading": s.heading, "role": s.role, "pages": sorted(p + 1 for p in s.pages)}
                for s in self.sections
            ],
        }


def build_rows(path: Path | str | bytes) -> tuple[list[Row], list[float], list[float]]:
    """Every text line and rule of the file in reading order, plus the size of each page.

    A row is one baseline: the segments of a line set in columns (an employer on the left, its
    dates on the right) are one row, because they must always move together.
    """
    lines, sizes = read_lines(path)  # type: ignore[arg-type]
    paragraphs = group_paragraphs(lines)
    owner: dict[int, tuple[PParagraph, int]] = {}
    for par in paragraphs:
        for index, line in enumerate(par.lines):
            owner[id(line)] = (par, index)
    rows: list[Row] = []
    by_baseline: dict[tuple[int, int], Row] = {}
    for line in sorted(lines, key=lambda ln: (ln.page, ln.baseline, ln.bbox[0])):
        key = (line.page, round(line.baseline / 1.6))
        near = next(
            (
                by_baseline[k]
                for k in ((key[0], key[1] - 1), key, (key[0], key[1] + 1))
                if k in by_baseline and abs(by_baseline[k].baseline - line.baseline) <= 1.6
            ),
            None,
        )
        if near is not None:
            near.top = min(near.top, line.bbox[1])
            near.bottom = max(near.bottom, line.bbox[3])
            near.left, near.right = min(near.left, line.bbox[0]), max(near.right, line.bbox[2])
            near.text = near.text + " " + line.text
            near.heading = False
            continue
        par, index = owner.get(id(line), (None, 0))
        row = Row(
            line.page,
            line.bbox[1],
            line.bbox[3],
            "text",
            line.baseline,
            line.text,
            is_heading(line.text),
            line,
            par,
            index,
            line.bbox[0],
            line.bbox[2],
        )
        by_baseline[key] = row
        rows.append(row)
    for page, rules in enumerate(pdf_read.rules(path)):
        for x0, y0, x1, y1 in rules:
            rows.append(Row(page, y0, y1, "rule", y1, "", False, None, None, 0, x0, x1))
    rows.sort(key=lambda r: (r.page, r.top, r.left))
    return rows, [s[0] for s in sizes], [s[1] for s in sizes]


def build_sections(rows: list[Row]) -> list[Section]:
    """Group rows under their section headings. A rule just above a heading belongs to it."""
    sections: list[Section] = []
    current = Section("", "other", [])
    for row in rows:
        if row.kind == "text" and row.heading:
            # Pull a separator that sits directly above the heading out of the previous section.
            pulled: list[Row] = []
            while (
                current.rows
                and current.rows[-1].kind == "rule"
                and (
                    (current.rows[-1].page == row.page
                    and 0 <= row.top - current.rows[-1].bottom <= _RULE_REACH)
                    or current.rows[-1].page != row.page
                )
            ):
                pulled.insert(0, current.rows.pop())
            if current.rows or current.heading:
                sections.append(current)
            current = Section(row.text, section_role(row.text), [*pulled, row])
            continue
        current.rows.append(row)
    if current.rows or current.heading:
        sections.append(current)
    return sections


def _rule_one(sections: list[Section]) -> RuleResult:
    edu = next((s for s in sections if s.role == "education"), None)
    work = next((s for s in sections if s.role == "work"), None)
    if edu is None or work is None:
        return RuleResult(
            "education_and_work_same_page",
            True,
            False,
            "No Education and Work sections to compare.",
        )
    pages = edu.pages | work.pages
    if len(pages) == 1:
        return RuleResult(
            "education_and_work_same_page",
            True,
            True,
            f"Both sections start and end on page {next(iter(pages)) + 1}.",
        )
    return RuleResult(
        "education_and_work_same_page",
        False,
        True,
        f"Education is on page(s) {sorted(p + 1 for p in edu.pages)} and Work on page(s) "
        f"{sorted(p + 1 for p in work.pages)}: together they run across pages "
        f"{sorted(p + 1 for p in pages)}.",
    )


def _rule_two(rows: list[Row], sections: list[Section]) -> RuleResult:
    extra = next((s for s in sections if s.role == "extra"), None)
    if extra is None:
        return RuleResult("extra_curricular_new_page", True, False, "No Extra-Curricular section.")
    heading = next(r for r in extra.rows if r.kind == "text")
    above = [
        r for r in rows if r.page == heading.page and r.kind == "text" and r.top < heading.top - 0.5
    ]
    if not above:
        return RuleResult(
            "extra_curricular_new_page",
            True,
            True,
            f"Starts at the top of page {heading.page + 1}.",
        )
    return RuleResult(
        "extra_curricular_new_page",
        False,
        True,
        f"Starts part-way down page {heading.page + 1} (y={heading.top:.0f}pt) with other "
        f"content above it.",
    )


def _rule_three(rows: list[Row]) -> RuleResult:
    rules = [r for r in rows if r.kind == "rule"]
    if not rules:
        return RuleResult(
            "first_separator_on_page_one", True, False, "The file has no horizontal separators."
        )
    first = rules[0]
    if first.page == 0:
        return RuleResult(
            "first_separator_on_page_one", True, True, "The first separator is on page 1."
        )
    return RuleResult(
        "first_separator_on_page_one",
        False,
        True,
        f"The first separator is on page {first.page + 1}.",
    )


def _rule_four(rows: list[Row], pages: int) -> RuleResult:
    problems: list[str] = []
    texts = [r for r in rows if r.kind == "text"]
    text_width = (max(r.right for r in texts) - min(r.left for r in texts)) if texts else 0.0
    for page in range(pages):
        # Only page-wide separators can be stranded; a table border belongs to its table.
        on_page = [
            r for r in rows if r.page == page and (r.kind == "text" or is_separator(r, text_width))
        ]
        text = [r for r in on_page if r.kind == "text"]
        if not on_page:
            continue
        for i, row in enumerate(text):
            if not row.heading:
                continue
            after = [r for r in text[i + 1 :] if not r.heading]
            ends_page = i + 1 + len(after) >= len(text)
            if not ends_page or len(after) >= _MIN_LINES_AFTER_HEADING:
                continue
            # A section whose whole body is one line is complete; one that goes on over the page
            # break (or has nothing under its heading) is stranded.
            global_rows = [r for r in rows if r.kind == "text"]
            position = next(k for k, r in enumerate(global_rows) if r is row)
            following = next((r for r in global_rows[position + 1 + len(after) :]), None)
            continues = (
                following is not None and not following.heading and following.page != row.page
            )
            if not after or continues:
                problems.append(
                    f"page {page + 1} ends with the heading '{row.text[:40]}' and only "
                    f"{len(after)} line(s) under it"
                )
        if on_page[-1].kind == "rule" and (not text or on_page[-1].top > text[-1].bottom):
            problems.append(f"a separator is left alone at the foot of page {page + 1}")
        if (
            on_page[0].kind == "rule"
            and page > 0
            and (len(on_page) < 2 or on_page[1].kind != "text")
        ):
            problems.append(f"a separator is left alone at the top of page {page + 1}")
    seen: dict[int, list[Row]] = {}
    for row in rows:
        if row.paragraph is not None and row.kind == "text":
            seen.setdefault(id(row.paragraph), []).append(row)
    for members in seen.values():
        if len(members) >= 2 and len({m.page for m in members}) > 1:
            first_page = members[0].page
            on_first = sum(1 for m in members if m.page == first_page)
            if on_first == 1 or len(members) - on_first == 1:
                problems.append(
                    f"a paragraph starting '{members[0].text[:36]}' leaves a single line on one "
                    f"page"
                )
    if problems:
        return RuleResult("no_orphans", False, True, "; ".join(dict.fromkeys(problems)))
    return RuleResult("no_orphans", True, True, "No stranded headings, separators or single lines.")


def _rule_five(rows: list[Row], pages: int) -> RuleResult:
    blank = [p + 1 for p in range(pages) if not any(r.kind == "text" for r in rows if r.page == p)]
    if blank:
        return RuleResult("no_blank_pages", False, True, f"Page(s) {blank} have no text.")
    return RuleResult("no_blank_pages", True, True, "Every page has content.")


def evaluate_rows(rows: list[Row], pages: int) -> tuple[list[Section], list[RuleResult]]:
    """Group ``rows`` into sections and judge them against every rule."""
    sections = build_sections(rows)
    rules = [
        _rule_one(sections),
        _rule_two(rows, sections),
        _rule_three(rows),
        _rule_four(rows, pages),
        _rule_five(rows, pages),
    ]
    return sections, rules


def analyse(path: Path | str | bytes) -> Pagination:
    """Measure a PDF against the pagination rules."""
    rows, widths, heights = build_rows(path)
    del widths
    pages = len(heights)
    sections, rules = evaluate_rows(rows, pages)
    tops = [min((r.top for r in rows if r.page == p), default=0.0) for p in range(pages)]
    bottoms = [max((r.bottom for r in rows if r.page == p), default=0.0) for p in range(pages)]
    return Pagination(
        pages,
        rows,
        sections,
        rules,
        min(tops, default=0.0),
        max(bottoms, default=0.0),
        heights[0] if heights else 0.0,
    )
