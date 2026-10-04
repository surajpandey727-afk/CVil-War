"""Will an ATS read this file correctly? (brief section 14)

Separate from content match on purpose: a beautiful résumé whose columns interleave, whose dates
do not parse or whose text is an image fails here whatever it says. The checks run on the actual
file when it is a PDF — text extraction, layout, images, odd characters — and on the parsed
structure for every format: section headings, contact details, dates and bullets.
"""
# ruff: noqa: RUF001
# The odd-character pattern must contain the characters it detects.

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.ats_engine.structure import Structure
from app.core.resume_tailoring.model import ResumeDocument

_WEIGHTS: dict[str, float] = {
    "text_extraction": 0.25,
    "sections": 0.20,
    "contact": 0.10,
    "dates": 0.15,
    "bullets": 0.10,
    "layout": 0.10,
    "graphics": 0.05,
    "characters": 0.05,
}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")
_LINK = re.compile(r"linkedin\.com|github\.com|https?://|www\.", re.I)
_ODD = re.compile(r"[�- ­​-‏  ]")


@dataclass
class ParsingReport:
    score: int
    checks: dict[str, int] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    file_checked: bool = False


def _pdf_signals(pdf: str | Path | bytes) -> dict[str, object]:
    """Facts about the PDF file itself."""
    from pypdf import PdfReader

    from app.core.resume_tailoring import pdf_read

    pages = pdf_read.read_chars(pdf)
    chars = [c for p in pages for c in p.chars]
    glyphs = [c for c in chars if not c.is_space]
    bad = sum(1 for c in glyphs if _ODD.search(c.c) and c.c not in " ­")
    odd = sum(1 for c in chars if _ODD.search(c.c))

    table_rows = column_rows = 0
    for page in pages:
        rows: dict[int, list] = {}
        for ch in page.chars:
            rows.setdefault(round(ch.oy / 2), []).append(ch)
        for row in rows.values():
            ink = sorted((c for c in row if not c.is_space), key=lambda c: c.x0)
            if len(ink) < 8:
                continue
            gaps = [
                (a.x1, b.x0)
                for a, b in zip(ink, ink[1:], strict=False)
                if b.x0 - a.x1 > 1.0 * max(a.size, b.size)
            ]
            segments = len(gaps) + 1
            if segments >= 3:
                table_rows += 1
            elif segments == 2:
                _end, start = gaps[0]
                left_len = sum(1 for c in ink if c.x1 <= gaps[0][0])
                if start > 0.45 * page.width and left_len > 20 and len(ink) - left_len > 20:
                    column_rows += 1
    images, big_images = 0, 0
    try:
        reader = PdfReader(io.BytesIO(pdf) if isinstance(pdf, (bytes, bytearray)) else str(pdf))
        for page in reader.pages:
            area = float(page.mediabox.width) * float(page.mediabox.height)
            for image in page.images:
                images += 1
                width, height = getattr(image.image, "size", (0, 0))
                if width * height > 0.25 * area * 4:
                    big_images += 1
    except Exception:  # an unreadable image table is not a reason to fail the whole check
        pass
    return {
        "glyphs": len(glyphs),
        "bad": bad,
        "odd": odd,
        "pages": len(pages),
        "table_rows": table_rows,
        "column_rows": column_rows,
        "images": images,
        "big_images": big_images,
    }


def parsing_report(
    doc: ResumeDocument, structure: Structure, pdf: str | Path | bytes | None = None
) -> ParsingReport:
    """Score how parseable the résumé is, with the reasons."""
    findings: list[str] = []
    checks: dict[str, int] = {}
    text = doc.to_text()

    signals = _pdf_signals(pdf) if pdf is not None else None
    if signals:
        glyphs = int(signals["glyphs"])
        if glyphs < 200:
            checks["text_extraction"] = 0
            findings.append("Almost no extractable text: the file may be a scan or an image.")
        else:
            bad_share = (int(signals["bad"])) / glyphs
            checks["text_extraction"] = round(100 * (1 - min(1.0, bad_share * 10)))
            if bad_share > 0.002:
                findings.append(f"{signals['bad']} glyphs extract as unreadable characters.")
    else:
        words = len(text.split())
        checks["text_extraction"] = 100 if words >= 120 else round(100 * words / 120)
        if words < 120:
            findings.append("Very little text could be read from the résumé.")

    kinds = set(structure.section_kinds)
    found = [k for k in ("experience", "education", "skills") if k in kinds]
    checks["sections"] = round(100 * len(found) / 3)
    for missing in ("experience", "education", "skills"):
        if missing not in kinds:
            findings.append(f"No clearly named {missing.title()} section was recognised.")

    head = " ".join(u.text for u in structure.of("header", "summary")[:12])
    email, phone, link = (
        bool(_EMAIL.search(head)),
        bool(_PHONE.search(head)),
        bool(_LINK.search(head)),
    )
    checks["contact"] = 50 * email + 30 * phone + 20 * link
    if not email:
        findings.append("No email address was found in the header.")
    if not phone:
        findings.append("No phone number was found in the header.")

    roles = structure.roles
    dated = [r for r in roles if r.start and r.end]
    checks["dates"] = 100 if not roles else round(100 * len(dated) / len(roles))
    if roles and len(dated) < len(roles):
        findings.append(
            f"{len(roles) - len(dated)} of {len(roles)} roles have dates that could not be parsed."
        )
    if not roles:
        checks["dates"] = 0
        findings.append("No roles with dates were found.")

    experience = structure.of("experience")
    bullets = [u for u in experience if u.kind.value == "bullet" and len(u.text.split()) >= 4]
    checks["bullets"] = (
        100
        if not experience
        else min(100, round(100 * len(bullets) / max(1, 0.6 * len(experience))))
    )
    if experience and len(bullets) < 0.4 * len(experience):
        findings.append("Experience is mostly not in bullet form, which parses less reliably.")

    if signals:
        rows, cols = int(signals["table_rows"]), int(signals["column_rows"])
        checks["layout"] = max(0, 100 - min(60, rows * 6) - min(40, cols * 4))
        if rows >= 3:
            findings.append(
                f"{rows} table-like rows: table cells often merge or reorder when parsed."
            )
        if cols >= 3:
            findings.append("A multi-column layout was detected; columns can interleave when read.")
        images, big = int(signals["images"]), int(signals["big_images"])
        checks["graphics"] = 100 if images == 0 else 70 if not big else 30
        if big:
            findings.append(
                "A large image covers part of the page; text inside images is invisible to an ATS."
            )
        odd = int(signals["odd"])
        share = odd / max(1, int(signals["glyphs"]))
        checks["characters"] = round(100 * (1 - min(1.0, share * 6)))
        if share > 0.01:
            findings.append("Non-breaking spaces or unusual characters appear in the text layer.")
    else:
        checks["layout"] = checks["graphics"] = 100
        share = len(_ODD.findall(text)) / max(1, len(text))
        checks["characters"] = round(100 * (1 - min(1.0, share * 6)))

    total = round(sum(checks[k] * w for k, w in _WEIGHTS.items()))
    return ParsingReport(total, checks, findings, file_checked=signals is not None)
