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

from app.core.resume_tailoring.model import LineKind, ResumeDocument

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


def render_docx(doc: ResumeDocument, out_path: Path) -> RenderResult:
    """Write the document out as a clean, structurally faithful DOCX.

    Used when the source was a PDF. Plain single-column output with real Word headings and
    real list paragraphs: the structure is the candidate's, the styling is ours, and no
    graphics, columns, icons or text boxes are introduced — all of which are the things that
    break ATS parsing.
    """
    from docx import Document as DocxDocument
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = DocxDocument()
    for style_name, size in (("Normal", 10), ("List Bullet", 10)):
        try:
            style = document.styles[style_name]
            style.font.name = "Calibri"
            style.font.size = Pt(size)
        except KeyError:
            pass

    # Header: name first and larger, then the contact lines exactly as the CV had them.
    for index, line in enumerate(doc.header):
        paragraph = document.add_paragraph()
        run = paragraph.add_run(line.text)
        run.bold = index == 0
        run.font.size = Pt(18 if index == 0 else 10)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(2)

    for section in doc.sections:
        if section.heading:
            heading = document.add_paragraph()
            run = heading.add_run(section.heading)
            run.bold = True
            run.font.size = Pt(12)
            heading.paragraph_format.space_before = Pt(10)
            heading.paragraph_format.space_after = Pt(4)

        for line in section.lines:
            if line.kind is LineKind.BULLET:
                paragraph = document.add_paragraph(line.text, style="List Bullet")
            else:
                paragraph = document.add_paragraph(line.text)
            paragraph.paragraph_format.space_after = Pt(2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out_path))
    logger.info("resume_docx_rendered", sections=len(doc.sections), path=str(out_path))
    return RenderResult(
        path=out_path,
        formatting_preserved=False,
        note=(
            "Source was a PDF, so the visual template could not be carried across. Section "
            "names, section order and every line are reproduced exactly."
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
