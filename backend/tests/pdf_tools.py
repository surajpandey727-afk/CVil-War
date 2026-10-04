"""Helpers for tests that inspect or deliberately damage PDF files (pypdf / pdfplumber / pdfium).

The damage helpers exist so the checker can be shown to catch real faults: a page that appears,
text that vanishes, words laid over other words, a rule where none belongs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from app.core.resume_tailoring import pdf_read
from app.core.resume_tailoring import pdf_stream as ps
from app.core.resume_tailoring.pdf_fonts import StandardFont
from app.core.resume_tailoring.pdf_write import FontRegistry


def pixels(path, page: int = 0, dpi: int = 96) -> np.ndarray:
    return pdf_read.render_gray(path, dpi)[page].astype(int)


def page_count(path) -> int:
    return len(PdfReader(str(path)).pages)


def raw_text(path) -> str:
    """The text layer exactly as extracted, whitespace characters untouched."""
    rows_out: list[str] = []
    for page in pdf_read.read_chars(path):
        rows: list[list[pdf_read.PChar]] = []
        for ch in sorted(page.chars, key=lambda c: (c.oy, c.x0)):
            if rows and abs(ch.oy - rows[-1][0].oy) <= 1.6:
                rows[-1].append(ch)
            else:
                rows.append([ch])
        rows_out += ["".join(c.c for c in sorted(r, key=lambda c: c.x0)) for r in rows]
    return "\n".join(rows_out)


def rules_on(path, page: int) -> list:
    return pdf_read.rules(path)[page]


def styles_in(path, page: int, rect: tuple[float, float, float, float]) -> set[tuple[str, float, int]]:
    """(font, size, colour) of every letter drawn inside ``rect`` (font without its subset prefix)."""
    from app.core.resume_tailoring.pdf_fonts import norm_name

    out = set()
    for ch in pdf_read.read_chars(path)[page].chars:
        inside = rect[0] <= (ch.x0 + ch.x1) / 2 <= rect[2] and rect[1] <= (ch.y0 + ch.y1) / 2 <= rect[3]
        if inside and ch.c.strip():
            out.add((norm_name(ch.font), round(ch.size, 1), ch.color))
    return out


def _append(src, dst, page: int, build) -> Path:
    writer = PdfWriter(clone_from=str(src))
    target = writer.pages[page]
    fonts = FontRegistry(writer)
    data = target.get_contents().get_data()
    extra = build(fonts, float(target.mediabox.height))
    stream = DecodedStreamObject()
    stream.set_data(data + b"\nq\n" + extra + b"\nQ\n")
    target[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    fonts.finalize()
    with open(dst, "wb") as handle:
        writer.write(handle)
    return Path(dst)


def with_extra_page(src, dst) -> Path:
    writer = PdfWriter(clone_from=str(src))
    writer.add_blank_page(612, 792)
    with open(dst, "wb") as handle:
        writer.write(handle)
    return Path(dst)


def with_text_removed(src, dst, line) -> Path:
    """Copy of ``src`` with the glyphs of one ``PLine`` taken out of the page content."""
    writer = PdfWriter(clone_from=str(src))
    page = writer.pages[line.page]
    ops = ps.parse(page.get_contents().get_data())
    fonts = {
        k.lstrip("/"): ps.metrics_for(v.get_object()) for k, v in (page["/Resources"].get("/Font") or {}).items()
    }
    interp = ps.Interpreter(ops, fonts)
    height = float(page.mediabox.height)
    doomed = {
        i for i, g in enumerate(interp.glyphs)
        if abs((height - g.y) - line.baseline) <= 1.5 and line.bbox[0] - 0.3 <= (g.x0 + g.x1) / 2 <= line.bbox[2] + 0.3
    }
    new = ps.remove_glyphs(ops, interp, doomed)
    stream = DecodedStreamObject()
    stream.set_data(ps.join([o for o in new if o is not None]))
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    with open(dst, "wb") as handle:
        writer.write(handle)
    return Path(dst)


def with_overlaid_text(src, dst, page: int, x: float, baseline: float, text: str, size: float = 10) -> Path:
    def build(fonts: FontRegistry, height: float) -> bytes:
        font = StandardFont("Helvetica")
        name = fonts.name_for(page, font)
        return b" ".join([b"BT", f"/{name} {size} Tf {x} {height - baseline} Td".encode(), ps.literal(text.encode("latin-1")), b"Tj ET"])

    return _append(src, dst, page, build)


def with_rule(src, dst, page: int, y_from_top: float, x0: float = 60, x1: float = 500) -> Path:
    def build(fonts: FontRegistry, height: float) -> bytes:
        return f"0.8 w {x0} {height - y_from_top} m {x1} {height - y_from_top} l S".encode()

    return _append(src, dst, page, build)


def flat_text(source) -> str:
    """All of a PDF's text on one line, for substring assertions (``source``: path or bytes)."""
    return " ".join(pdf_read.page_texts(source)).replace("\n", " ")


def page_boxes(source) -> list[tuple[float, float]]:
    return pdf_read.page_sizes(source)


def word_counts(source) -> list[int]:
    return [len(w) for w in pdf_read.words(source)]
