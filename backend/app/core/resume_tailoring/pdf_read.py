"""Read a PDF page as glyphs, drawn rules and pixels.

Everything that looks at the PDF but does not change it goes through here, so the rest of the
tailoring code never touches a PDF library directly. Text and geometry come from pdfplumber (MIT,
on pdfminer.six); pixels come from pypdfium2 (Apache-2.0 / BSD-3). Neither is copyleft, which is
why they are used instead of the AGPL PyMuPDF this module replaced.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pdfplumber
import pypdfium2 as pdfium

#: Where a glyph's box sits relative to its baseline, as a share of the font size. pdfminer's own
#: box is exactly one font size tall and floats with the font descent; a fixed ascent/descent
#: pair is steadier for judging whether two lines are neighbours.
_ASCENT = 0.9
_DESCENT = 0.22
#: A gap wider than this share of the font size between two glyphs with no space glyph between
#: them is a word break (PDFs that position words individually carry no space characters).
_SYNTHETIC_SPACE = 0.18
#: ``PChar.flags`` bit marking a space that was inferred from a gap, not drawn by the file.
SYNTHETIC = 1


@dataclass(slots=True)
class PChar:
    """One glyph on the page."""

    c: str
    x0: float
    y0: float
    x1: float
    y1: float
    oy: float  # baseline, measured from the top of the page
    font: str
    size: float
    color: int
    flags: int = 0

    @property
    def is_space(self) -> bool:
        return self.c.isspace()


@dataclass
class PageChars:
    width: float
    height: float
    chars: list[PChar]


def _color(value: object) -> int:
    """A pdfplumber colour (gray, rgb or cmyk tuple) as 0xRRGGBB."""
    if not isinstance(value, (tuple, list)) or not value:
        return 0
    comps = [float(v) for v in value if isinstance(v, (int, float))]
    if len(comps) == 1:
        comps = comps * 3
    elif len(comps) == 4:
        c, m, y, k = comps
        comps = [(1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)]
    if len(comps) != 3:
        return 0
    r, g, b = (max(0, min(255, round(v * 255))) for v in comps)
    return (r << 16) | (g << 8) | b


def _source(path: Path | str | bytes) -> io.BytesIO | str:
    """What pdfplumber / pdfium open: a path, or the bytes of a file held in memory."""
    return io.BytesIO(path) if isinstance(path, (bytes, bytearray)) else str(path)


def _to_pchar(raw: dict, height: float) -> PChar:
    text = raw["text"]
    if text.startswith("(cid:"):
        text = "�"
    size = float(raw.get("size") or 0.0)
    baseline = height - float(raw["matrix"][5]) if raw.get("matrix") else float(raw["bottom"])
    return PChar(
        text,
        float(raw["x0"]),
        baseline - _ASCENT * size,
        float(raw["x1"]),
        baseline + _DESCENT * size,
        baseline,
        raw.get("fontname") or "",
        size,
        _color(raw.get("non_stroking_color")),
    )


def _with_word_breaks(chars: list[PChar]) -> list[PChar]:
    """Insert a space between glyphs that sit on one baseline with a word-sized gap and none.

    A line set in one run per word carries no space glyphs, and without them the line's words
    run together into one token in the text layer and in every comparison made against it.
    """
    ordered = sorted(chars, key=lambda c: (round(c.oy, 0), c.x0))
    out: list[PChar] = []
    for ch in ordered:
        prev = out[-1] if out else None
        if (
            prev is not None
            and not prev.is_space
            and not ch.is_space
            and abs(prev.oy - ch.oy) <= 1.0
            and ch.x0 - prev.x1 > _SYNTHETIC_SPACE * max(prev.size, ch.size)
        ):
            out.append(
                PChar(
                    " ",
                    prev.x1,
                    prev.y0,
                    ch.x0,
                    prev.y1,
                    prev.oy,
                    prev.font,
                    prev.size,
                    prev.color,
                    SYNTHETIC,
                )
            )
        out.append(ch)
    return out


def read_chars(path: Path | str | bytes) -> list[PageChars]:
    """Every page's glyphs, with the geometry the layout code needs."""
    pages: list[PageChars] = []
    with pdfplumber.open(_source(path)) as pdf:
        for page in pdf.pages:
            height = float(page.height)
            chars = [_to_pchar(raw, height) for raw in page.chars if raw.get("text")]
            pages.append(PageChars(float(page.width), height, _with_word_breaks(chars)))
    return pages


def page_sizes(path: Path | str | bytes) -> list[tuple[float, float]]:
    with pdfplumber.open(_source(path)) as pdf:
        return [(float(p.width), float(p.height)) for p in pdf.pages]


def rules(path: Path | str | bytes) -> list[list[tuple[float, float, float, float]]]:
    """Horizontal separators per page: thin filled or stroked rectangles and lines."""
    out: list[list[tuple[float, float, float, float]]] = []
    with pdfplumber.open(_source(path)) as pdf:
        for page in pdf.pages:
            found: list[tuple[float, float, float, float]] = []
            for item in [*page.rects, *page.lines, *page.curves]:
                width, height = item["x1"] - item["x0"], item["bottom"] - item["top"]
                if height <= 3.0 and width >= 40:
                    found.append(
                        (
                            round(item["x0"], 1),
                            round(item["top"], 1),
                            round(item["x1"], 1),
                            round(item["bottom"], 1),
                        )
                    )
            out.append(sorted(set(found)))
    return out


def words(path: Path | str | bytes) -> list[list[tuple[float, float, float, float]]]:
    """Word boxes per page, in page points."""
    out: list[list[tuple[float, float, float, float]]] = []
    for page in read_chars(path):
        boxes: list[tuple[float, float, float, float]] = []
        run: list[PChar] = []
        for ch in [*sorted(page.chars, key=lambda c: (round(c.oy, 0), c.x0)), None]:
            if ch is not None and not ch.is_space and (not run or abs(ch.oy - run[-1].oy) <= 1.0):
                run.append(ch)
                continue
            if run:
                boxes.append(
                    (
                        min(c.x0 for c in run),
                        min(c.y0 for c in run),
                        max(c.x1 for c in run),
                        max(c.y1 for c in run),
                    )
                )
            run = [ch] if ch is not None and not ch.is_space else []
        out.append(boxes)
    return out


def page_texts(path: Path | str | bytes) -> list[str]:
    """Each page's text in reading order (rows top to bottom, left to right within a row)."""
    out: list[str] = []
    for page in read_chars(path):
        rows: list[list[PChar]] = []
        for ch in sorted(page.chars, key=lambda c: (c.oy, c.x0)):
            if rows and abs(ch.oy - rows[-1][0].oy) <= 1.6:
                rows[-1].append(ch)
            else:
                rows.append([ch])
        out.append(
            "\n".join(
                re.sub(r"\s+", " ", "".join(c.c for c in sorted(r, key=lambda c: c.x0))).strip()
                for r in rows
            )
        )
    return out


def render_gray(path: Path | str | bytes, dpi: int) -> list[np.ndarray]:
    """Each page rendered to a grey-level array at ``dpi``."""
    pdf = pdfium.PdfDocument(path if isinstance(path, (bytes, bytearray)) else str(path))
    try:
        return [_gray_page(pdf[i], dpi) for i in range(len(pdf))]
    finally:
        pdf.close()


def _gray_page(page: pdfium.PdfPage, dpi: int) -> np.ndarray:
    arr = np.asarray(page.render(scale=dpi / 72.0, grayscale=True).to_numpy())
    return arr.reshape(arr.shape[0], arr.shape[1]).astype(np.int16)
