"""Write a tailored document back out, keeping as much of the original as the source allows.

Two paths, because the honest answer depends on what was uploaded.

**A DOCX source is edited in place.** The original file is opened and only the paragraphs whose
text actually changed are rewritten, run by run, so fonts, spacing, columns, tables, headers
and the candidate's whole visual template survive untouched. This is the path that satisfies
"the output must still look like my CV" literally rather than approximately.

**A PDF source is re-rendered structurally.** A PDF cannot be edited back into itself without
a full layout engine, so the output is a clean Word document that reproduces the *structure*
exactly — the same section headings, in the same order, with the same lines and the same
bullets. What cannot be carried across is the visual design, and that limitation is reported
rather than glossed over.

Neither path invents a section, reorders one, or renames one. The document model already
forbids that; this module only writes down what the model holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from app.core.resume_tailoring.model import Line, LineKind, ResumeDocument, Style

logger = structlog.get_logger(__name__)


@dataclass
class RenderResult:
    path: Path
    #: True when the original file's own formatting was preserved byte-for-byte outside the
    #: edited paragraphs.
    formatting_preserved: bool
    #: Paragraphs whose text was replaced.
    paragraphs_edited: int = 0
    note: str = ""


def _set_paragraph_text(paragraph: object, text: str) -> None:
    """Replace a paragraph's text while keeping its formatting.

    The first run keeps its character formatting and receives the new text; the remaining runs
    are emptied rather than deleted, because deleting runs can drop the bullet's numbering
    properties along with them and turn a list item into a bare paragraph.
    """
    if not paragraph.runs:
        paragraph.text = text
        return
    paragraph.runs[0].text = text
    for run in paragraph.runs[1:]:
        run.text = ""


def edit_docx_in_place(
    source: str | Path, original: ResumeDocument, tailored: ResumeDocument, out_path: Path
) -> RenderResult:
    """Apply the changed lines to the uploaded DOCX, leaving everything else alone."""
    from docx import Document as DocxDocument

    before = {ln.id: ln.text for ln in original.all_lines()}
    changed = {
        before[ln.id]: ln.text
        for ln in tailored.all_lines()
        if ln.id in before and before[ln.id] != ln.text
    }

    document = DocxDocument(str(source))
    edited = 0

    def visit(paragraph: object) -> None:
        nonlocal edited
        current = paragraph.text.strip()
        if not current:
            return
        replacement = changed.get(current)
        if replacement is None:
            # The document model strips bullet glyphs; the file may still carry one inline.
            for old, new in changed.items():
                if old and old in current:
                    replacement = current.replace(old, new)
                    break
        if replacement and replacement != current:
            _set_paragraph_text(paragraph, replacement)
            edited += 1

    for paragraph in document.paragraphs:
        visit(paragraph)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    visit(paragraph)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out_path))
    logger.info("resume_docx_edited_in_place", edited=edited, path=str(out_path))
    return RenderResult(
        path=out_path,
        formatting_preserved=True,
        paragraphs_edited=edited,
        note="Original DOCX edited in place; formatting untouched outside changed lines.",
    )


def _dominant_body_style(doc: ResumeDocument) -> Style:
    """The typography most of the document's body text uses.

    Used for the document default, so anything this module does not style explicitly still
    comes out in the candidate's typeface rather than Word's.
    """
    from collections import Counter

    tally: Counter[tuple[str, float]] = Counter()
    for line in doc.all_lines():
        st = line.style
        if st.font and st.size:
            tally[(st.font, st.size)] += max(1, len(line.text))
    if not tally:
        return Style(font="Calibri", size=10.0)
    font, size = tally.most_common(1)[0][0]
    return Style(font=font, size=size)


def _apply(run, style: Style, fallback: Style) -> None:
    """Put one line's typography onto a Word run."""
    from docx.shared import Pt, RGBColor

    run.font.name = style.font or fallback.font or None
    size = style.size or fallback.size
    if size:
        run.font.size = Pt(size)
    run.bold = style.bold
    run.italic = style.italic
    if style.colour:
        run.font.color.rgb = RGBColor(*style.colour)

    # python-docx sets the Latin typeface only; East Asian and complex-script slots fall back
    # to the theme font, and Word then renders the line in Calibri on some machines and the
    # right face on others. Setting all three makes the document look the same everywhere.
    if run.font.name:
        from docx.oxml.ns import qn

        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = rpr.makeelement(qn("w:rFonts"), {})
            rpr.append(rfonts)
        for slot in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rfonts.set(qn(slot), run.font.name)


def _align(paragraph, style: Style) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    if style.align == "center":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif style.align == "right":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def render_docx(doc: ResumeDocument, out_path: Path) -> RenderResult:
    """Write the document out in the typography it arrived with.

    Used when the source was a PDF, which cannot be edited back into itself. What is
    reproduced is not just the structure but the look: the same typeface, sizes, weights,
    colours, alignment and section spacing the candidate's own CV uses.

    The renderer this replaces hard-coded Calibri 10pt in black. Run against a CV set in
    Times New Roman with 20pt teal headings, it returned a document that shared none of those
    things -- correct words, somebody else's CV.
    """
    from docx import Document as DocxDocument
    from docx.shared import Pt

    body = _dominant_body_style(doc)
    document = DocxDocument()

    normal = document.styles["Normal"]
    normal.font.name = body.font or "Calibri"
    normal.font.size = Pt(body.size or 10.0)

    # Margins follow the source's own text block rather than Word's one-inch default, which
    # would reflow a carefully fitted three-page CV onto four.
    if doc.page_margins:
        section = document.sections[0]
        left, right, top, bottom = doc.page_margins
        section.left_margin = Pt(left)
        section.right_margin = Pt(right)
        section.top_margin = Pt(top)
        section.bottom_margin = Pt(bottom)

    def emit(line: Line, *, bullet: bool) -> None:
        if bullet:
            paragraph = document.add_paragraph(style="List Bullet")
        else:
            paragraph = document.add_paragraph()
        run = paragraph.add_run(line.text)
        _apply(run, line.style, body)
        _align(paragraph, line.style)
        paragraph.paragraph_format.space_after = Pt(0)
        if line.style.space_before:
            paragraph.paragraph_format.space_before = Pt(min(line.style.space_before, 14))
        else:
            paragraph.paragraph_format.space_before = Pt(0)

    for line in doc.header:
        emit(line, bullet=False)

    for section in doc.sections:
        if section.heading:
            heading = document.add_paragraph()
            run = heading.add_run(section.heading)
            _apply(run, section.heading_style, body)
            _align(heading, section.heading_style)
            heading.paragraph_format.space_before = Pt(
                min(section.heading_style.space_before or 8, 14)
            )
            heading.paragraph_format.space_after = Pt(2)

        for line in section.lines:
            emit(line, bullet=line.kind is LineKind.BULLET)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out_path))
    logger.info(
        "resume_docx_rendered",
        sections=len(doc.sections),
        font=body.font,
        size=body.size,
        path=str(out_path),
    )
    return RenderResult(
        path=out_path,
        formatting_preserved=bool(body.font and body.font != "Calibri"),
        note=(
            f"Rebuilt from a PDF in the source's own typography ({body.font} {body.size:g}pt), "
            "with its section names, order, colours and alignment. Exact page geometry cannot "
            "be carried across from a PDF."
        ),
    )


def verify_rendered(path: Path, expected: ResumeDocument) -> list[str]:
    """Re-read the written file and check nothing was lost on the way out.

    The document that gets submitted has to be the document that was validated, so this
    reparses the actual artefact rather than trusting the in-memory model that produced it.
    """
    from app.core.resume_tailoring.extract import extract_from_docx

    problems: list[str] = []
    reparsed = extract_from_docx(str(path))
    text = reparsed.to_text().lower()

    for heading in expected.headings():
        if heading.lower() not in text:
            problems.append(f"section heading missing after export: {heading!r}")

    for line in expected.all_lines():
        probe = line.text.strip()
        if len(probe) < 15:
            continue
        # Compare on a distinctive opening fragment: exporters normalise whitespace and
        # punctuation, and a whole-line equality check would fail on cosmetics alone.
        fragment = " ".join(probe.split()[:6]).lower()
        if fragment and fragment not in text:
            problems.append(f"content missing after export: {probe[:60]!r}")

    return problems
