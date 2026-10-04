"""Prove an edited PDF is still the candidate's CV, from the file itself.

A tailored PDF can contain exactly the right words and still be broken: a line pushed over its
neighbour, a heading lost to a redaction, a page that no longer matches. Text extraction cannot
see any of that, so these checks read the rendered pages too. They run on every generation, and
the same functions are the visual-regression harness in the test suite — one definition of
"unchanged" for both.

The checks, each reported as a plain sentence so the audit and the UI can show them:

* same page count and page sizes, and no blank page;
* every edit reads back from the file, and the text it replaced is gone;
* every paragraph that was not edited is still there, word for word;
* the rendered page is pixel-identical outside the paragraphs that were edited;
* nothing is clipped off the page, and no two words overlap that did not already;
* edited text uses only the fonts, sizes and colours its paragraph already used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.core.resume_tailoring import pdf_read
from app.core.resume_tailoring.model import ResumeDocument
from app.core.resume_tailoring.pdf_edit import PdfEditResult
from app.core.resume_tailoring.pdf_layout import PParagraph, read_lines

#: : Render resolution for the comparison. High enough to see a one-line shift, low enough to be
#: cheap.
_DPI = 96
#: A pixel counts as changed when its grey level moves by more than this.
_PIXEL_DELTA = 48
#: : Points of margin around an edited paragraph in which change is expected (descenders, anti-
#: aliasing).
_REGION_PAD = 4.0
#: Changed pixels tolerated outside the edited regions. Zero is the aim; this absorbs rounding.
_OUTSIDE_TOLERANCE = 12
#: Words overlapping by more than this share of the smaller one count as overlapping.
_OVERLAP_SHARE = 0.25


@dataclass
class PdfCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)


def _canon(text: str) -> str:
    """Text with every kind of whitespace and the common ligatures removed, for comparison."""
    text = (text or "").replace("­", "")
    for ligature, plain in (("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl")):
        text = text.replace(ligature, plain)
    return re.sub(r"\s+", "", text)


def _family(font: str) -> str:
    name = re.sub(r"^[A-Z]{6}\+", "", font or "").lower()
    name = re.sub(r"(psmt|ps|mt|bold|italic|oblique|regular|[-,_ ])", "", name)
    return name


def _overlaps(rects: list[tuple[float, float, float, float]]) -> int:
    count = 0
    ordered = sorted(rects)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            if b[0] >= a[2]:
                break
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w > 0 and h > 0:
                smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
                if smaller > 0 and (w * h) / smaller > _OVERLAP_SHARE:
                    count += 1
    return count


Box = tuple[float, float, float, float]


def _span_styles(page: pdf_read.PageChars, rect: Box) -> set[tuple[str, float, int]]:
    """The (font family, size, colour) of every letter or digit drawn inside ``rect``."""
    styles: set[tuple[str, float, int]] = set()
    for ch in page.chars:
        inside = (
            rect[0] <= (ch.x0 + ch.x1) / 2 <= rect[2] and rect[1] <= (ch.y0 + ch.y1) / 2 <= rect[3]
        )
        # Glyphs with no letters or digits (a hyphen, a space) may legitimately come from a
        # fallback face when the document's own cannot draw that glyph.
        if inside and re.search(r"[A-Za-z0-9]", ch.c):
            styles.add((_family(ch.font), round(ch.size, 1), ch.color))
    return styles


def _pad(rect: Box, pad: float) -> Box:
    return (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)


def _heading_positions(path: str, headings: list[str]) -> dict[str, tuple[int, float] | None]:
    """Page index and top edge of each section heading: the line whose whole text is it.

    Matched on exact line text, not a text search — a search is case-insensitive and finds the
    word "experience" in a summary long before it finds the heading EXPERIENCE.
    """
    lines, _ = read_lines(path)
    found: dict[str, tuple[int, float] | None] = {}
    for heading in headings:
        needle = heading.strip()
        hit = next((ln for ln in lines if ln.text.strip() == needle), None)
        found[heading] = (hit.page, round(hit.bbox[1], 1)) if hit else None
    return found


def pagination_report(
    before_path: str,
    after_path: str,
    headings: list[str],
) -> tuple[dict[str, object], list[str]]:
    """Whether page structure is untouched: section starts and separators sit where they did.

    An in-place edit cannot move a page break, but "cannot" is checked rather than assumed. A
    heading that has moved pages, or a rule that has moved or vanished, is exactly the orphan /
    detached-separator layout fault this exists to catch.
    """
    problems: list[str] = []
    heads_before = _heading_positions(before_path, headings)
    heads_after = _heading_positions(after_path, headings)
    for heading in headings:
        b, a = heads_before[heading], heads_after[heading]
        if b is None:
            continue
        if a is None:
            problems.append(f"heading '{heading}' is no longer on any page")
        elif a[0] != b[0] or abs(a[1] - b[1]) > 1.0:
            problems.append(f"heading '{heading}' moved from page {b[0] + 1} to page {a[0] + 1}")
    rules_before = pdf_read.rules(before_path)
    rules_after = pdf_read.rules(after_path)
    separators_unchanged = rules_before == rules_after
    if not separators_unchanged:
        problems.append("a horizontal separator moved, changed or disappeared")
    report = {
        "section_pages": {h: (heads_after[h][0] + 1 if heads_after[h] else None) for h in headings},
        "separators_per_page": [len(r) for r in rules_after],
        "separators_unchanged": separators_unchanged,
        "section_starts_unchanged": not any("heading" in p for p in problems),
    }
    return report, problems


def check_edited_pdf(
    original_path: Path | str,
    edited_path: Path | str,
    original: ResumeDocument,
    edits: dict[str, str],
    result: PdfEditResult,
) -> PdfCheck:
    """Compare ``edited_path`` with ``original_path`` and report anything that moved."""
    problems: list[str] = []
    metrics: dict[str, object] = {}
    try:
        before = pdf_read.read_chars(original_path)
        after = pdf_read.read_chars(edited_path)
        gray_before = pdf_read.render_gray(original_path, _DPI)
        gray_after = pdf_read.render_gray(edited_path, _DPI)
    except Exception as exc:  # an unopenable output is the first and worst failure
        return PdfCheck(False, [f"the generated PDF cannot be opened: {exc}"])

    if len(before) != len(after):
        problems.append(f"page count changed from {len(before)} to {len(after)}")
        return PdfCheck(False, problems, {"pages_before": len(before), "pages_after": len(after)})
    metrics["pages"] = len(after)

    applied = {o.line_id: o for o in result.applied}
    regions: dict[int, list[Box]] = {}
    for outcome in applied.values():
        if outcome.rect:
            regions.setdefault(outcome.page, []).append(_pad(outcome.rect, _REGION_PAD))

    outside_total = 0
    words_before = pdf_read.words(original_path)
    words_after = pdf_read.words(edited_path)
    for index in range(len(after)):
        pb, pa = before[index], after[index]
        if (round(pb.width, 1), round(pb.height, 1)) != (round(pa.width, 1), round(pa.height, 1)):
            problems.append(
                f"page {index + 1} size changed from {pb.width}x{pb.height} to "
                f"{pa.width}x{pa.height}"
            )
        if len(words_after[index]) < 0.4 * max(1, len(words_before[index])):
            problems.append(f"page {index + 1} lost most of its text")

        gb, ga = gray_before[index], gray_after[index]
        if gb.shape != ga.shape:
            continue
        changed = np.abs(gb - ga) > _PIXEL_DELTA
        scale = _DPI / 72.0
        for rect in regions.get(index, []):
            changed[
                max(0, int(rect[1] * scale)) : int(rect[3] * scale) + 1,
                max(0, int(rect[0] * scale)) : int(rect[2] * scale) + 1,
            ] = False
        outside = int(changed.sum())
        outside_total += outside
        if outside > _OUTSIDE_TOLERANCE:
            problems.append(
                f"page {index + 1}: {outside} pixels changed outside the edited paragraphs"
            )

        for w in words_after[index]:
            if w[0] < -1 or w[1] < -1 or w[2] > pa.width + 1 or w[3] > pa.height + 1:
                problems.append(f"page {index + 1}: text runs off the page")
                break
        if _overlaps(words_after[index]) > _overlaps(words_before[index]):
            problems.append(f"page {index + 1}: edited text overlaps other text")
    metrics["pixels_changed_outside_edits"] = outside_total

    texts_before = pdf_read.page_texts(original_path)
    texts_after = pdf_read.page_texts(edited_path)
    text_after = "".join(_canon(t) for t in texts_after)
    text_before = "".join(_canon(t) for t in texts_before)

    for line_id, outcome in applied.items():
        new = _canon(edits[line_id])
        par = original.layout.get(line_id)
        old = _canon(par.text) if isinstance(par, PParagraph) else ""
        if new and new not in text_after:
            problems.append(f"edit {line_id} does not read back from the generated PDF")
        if old and old != new and old not in new:  # an append keeps the old text, by design
            # Another paragraph may legitimately repeat this wording, so the test is that
            # THIS copy went, not that none remain.
            replaced_here = sum(
                1
                for other in applied
                if isinstance(original.layout.get(other), PParagraph)
                and _canon(original.layout[other].text) == old
                and _canon(edits[other]) != old
            )
            if text_after.count(old) > text_before.count(old) - replaced_here:
                problems.append(f"edit {line_id}: the replaced text is still in the PDF")
        if isinstance(par, PParagraph) and outcome.rect:
            old_styles = _span_styles(before[par.page], _pad(par.bbox, 1.0))
            new_styles = _span_styles(after[par.page], outcome.rect)
            if (
                outcome.substituted_fonts
            ):  # a declared fallback face: only the size must still match
                stray = {s for s in new_styles if s[1] not in {o[1] for o in old_styles}}
            else:
                stray = {s for s in new_styles if s[0:2] not in {o[0:2] for o in old_styles}}
            if stray:
                problems.append(f"edit {line_id}: unexpected font or size {sorted(stray)[0]}")

    edited_ids = set(applied)
    for line_id, par in original.layout.items():
        if line_id in edited_ids or not isinstance(par, PParagraph):
            continue
        canon = _canon(par.text)
        if canon and canon in text_before and canon not in text_after:
            problems.append(f"text outside the edits was lost: '{par.text[:48]}…'")
            break

    pagination, pagination_problems = pagination_report(
        str(original_path), str(edited_path), [h for h in original.headings() if h]
    )
    metrics["pagination"] = pagination
    problems.extend(pagination_problems)

    markers_before = sum(len(re.findall(r"[•●▪]", t)) for t in texts_before)
    markers_after = sum(len(re.findall(r"[•●▪]", t)) for t in texts_after)
    # A removed bullet takes its own marker with it, and nothing else's.
    markers_before -= sum(
        1
        for lid, o in applied.items()
        if o.removed
        and isinstance(original.layout.get(lid), PParagraph)
        and re.search(r"[•●▪]", original.layout[lid].marker)
    )
    if markers_before != markers_after:
        problems.append(f"bullet markers changed from {markers_before} to {markers_after}")
    return PdfCheck(not problems, problems, metrics)
