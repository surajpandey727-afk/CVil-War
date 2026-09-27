"""Turn extracted CV text into a :class:`ResumeDocument` without discarding anything.

The rule that governs every decision here: **no line is ever dropped.** The parser this
replaces recognised a section only if its heading matched one of 24 exact strings and threw
away everything else, which on a real CV meant throwing away the entire CV. Recognising a
heading is therefore treated as an optimisation, not a gate — a heading we fail to spot costs
us a section boundary, never content.

Heading detection uses how the line is *written* rather than what it is *called*, so a CV is
free to name its sections whatever it likes. Two signals carry it, both chosen for precision
over recall since a missed heading is cheap and a false one fragments a section:

* the line is set in capitals, which is how the large majority of CVs mark a section, or
* the line ends in a colon, which is how most of the rest do.

Lines carrying an email, a URL or a date range are never headings however they are cased —
"Data Scientist → AI Product Manager June 2024 - Present" is a role line, not a section.
"""
# ruff: noqa: RUF001
# Bullet glyphs, en dashes and hyphen bullets appear as data here: these modules exist
# to recognise the characters real CVs are typeset with. ASCII look-alikes would stop
# them matching the documents they are written for.


from __future__ import annotations

import re

from app.core.resume_tailoring.model import (
    BULLET_PREFIX,
    Line,
    LineKind,
    ResumeDocument,
    Section,
    make_line,
)

#: Contact-detail patterns. Their presence disqualifies a line from being a heading and marks
#: it as part of the header block.
_EMAIL = re.compile(r"[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"(?:https?://|www\.|linkedin\.com|github\.com)", re.I)
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")

#: A month or a year range. Role lines carry these; section headings do not.
_DATE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{2,4}"
    r"|\b(19|20)\d{2}\s*[-–—]\s*((19|20)\d{2}|present|current|now)\b"
    r"|\b(19|20)\d{2}\b",
    re.I,
)

#: Headings are short. Anything longer is a sentence that happens to be capitalised.
_MAX_HEADING_CHARS = 64
_MAX_HEADING_WORDS = 8

#: Section names whose prose is the candidate's positioning statement, and may therefore be
#: re-pointed at a target role. Matched loosely because CVs name it many ways; an unnamed
#: block at the top of the document counts too.
_SUMMARY_HEADING = re.compile(
    r"\b(summary|profile|objective|about\s+me|professional\s+profile|personal\s+statement)\b",
    re.I,
)


def _uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def is_heading(raw: str) -> bool:
    """Whether a line introduces a new section.

    Deliberately conservative. A false positive splits one section into two and can strand an
    employer line under the wrong heading; a false negative merely merges two sections, and
    every line is still present and still in order.
    """
    text = raw.strip()
    if not text or len(text) > _MAX_HEADING_CHARS:
        return False
    if len(text.split()) > _MAX_HEADING_WORDS:
        return False
    if _EMAIL.search(text) or _URL.search(text) or _PHONE.search(text):
        return False
    if _DATE.search(text):
        return False
    # A heading is a label, not a sentence.
    if text.endswith((".", ",", ";")):
        return False
    if len([c for c in text if c.isalpha()]) < 3:
        return False

    if text.endswith(":"):
        return True
    # "EDUCATION & QUALIFICATIONS" / "WORK & LEADERSHIP EXPERIENCE".
    return _uppercase_ratio(text) >= 0.7


def _is_contact_line(text: str) -> bool:
    return bool(_EMAIL.search(text) or _URL.search(text) or _PHONE.search(text))


def _split_header(lines: list[str]) -> int:
    """How many leading lines are the contact block.

    The name and contact details are immutable and are not part of any section. The block ends
    at the last line within the opening run that still carries a contact detail — after that
    the document has started saying something, and on many CVs (this one included) what it
    says next is an unlabelled summary paragraph that must stay editable.
    """
    last_contact = -1
    for index, raw in enumerate(lines[:8]):
        if _is_contact_line(raw):
            last_contact = index
        elif is_heading(raw):
            break
    # Always keep at least the name line.
    return max(last_contact + 1, 1) if lines else 0


def parse_resume_text(text: str, *, source_format: str = "") -> ResumeDocument:
    """Parse extracted CV text into a faithful, editable document.

    Every non-blank line of the input appears exactly once in the result, in its original
    order. That property is asserted by the test suite, because it is the one the previous
    implementation violated catastrophically.
    """
    raw_lines = [ln for ln in (text or "").splitlines()]
    non_blank = [(i, ln) for i, ln in enumerate(raw_lines) if ln.strip()]
    if not non_blank:
        return ResumeDocument(source_format=source_format)

    ordered = [ln for _, ln in non_blank]
    header_len = _split_header(ordered)

    doc = ResumeDocument(source_format=source_format)
    counter = 0
    for raw in ordered[:header_len]:
        line = make_line(counter, raw)
        # Nothing in the contact block is ever edited, even if it looks like a bullet.
        line.kind = LineKind.FIXED
        doc.header.append(line)
        counter += 1

    #: The run of content before the first heading. Real CVs open with an unlabelled summary
    #: far more often than not, and the previous parser discarded exactly this.
    current = Section(heading="", order=0)
    order = 0

    for raw in ordered[header_len:]:
        if is_heading(raw):
            if current.lines or current.heading:
                doc.sections.append(current)
            order += 1
            current = Section(heading=raw.strip(), order=order)
            continue
        line = make_line(counter, raw)
        counter += 1
        current.lines.append(line)

    if current.lines or current.heading:
        doc.sections.append(current)

    _join_wrapped_lines(doc)
    _protect_skill_tables(doc)
    _classify_prose(doc)
    _join_prose(doc)
    return doc


#: A heading naming the skills block. Its content is usually a table, flattened by text
#: extraction into rows that superficially look like bullets. Editing those rows would
#: scramble the table, so the whole section is held immutable and keyword additions are
#: routed to experience bullets instead — which is where a recruiter reads them anyway.
#: Words that name a skills block. Substring matching, deliberately: word-boundary
#: patterns kept failing on the plural, and a heading is short enough that a substring
#: test is both sufficient and impossible to mis-escape.
_SKILLS_WORDS = ("skill", "competenc", "technolog", "technical", "highlight",
                 "proficienc", "toolkit", "stack")


def _is_skills_heading(heading: str) -> bool:
    """Whether this heading introduces the skills block."""
    low = heading.lower()
    return any(word in low for word in _SKILLS_WORDS)

#: An entry header: an employer, a role-and-dates line, a project sub-heading. These follow
#: bullets all the time and must never be swallowed into the bullet above them.
_ENTRY_HEADER_HINT = re.compile(
    r"\((?:Technology|Product|Engineering|Data)\s+Team\)|–|—", re.I
)


def _stitch(left: str, right: str) -> str:
    """Join two halves of a wrapped line.

    A trailing hyphen belongs to the word — extraction splits "Azure-based" across lines, and
    both dropping the hyphen ("Azurebased") and padding it ("Azure- based") corrupt a
    technology name that a recruiter and an ATS both search for verbatim.
    """
    left = left.rstrip()
    if left.endswith("-"):
        return f"{left}{right.lstrip()}"
    return f"{left} {right.lstrip()}".strip()


def _looks_like_continuation(previous: Line, raw: str) -> bool:
    """Whether ``raw`` is the wrapped remainder of the line above it.

    PDF text extraction breaks one résumé bullet across several physical lines. Left alone
    each fragment becomes its own line and only the first is editable, so an edit could
    rewrite the opening clause of a bullet and strand the rest — which reads far worse than
    no edit at all.

    Two signals decide it, and they cover the cases a CV actually produces: the previous line
    stopped mid-sentence, or this one starts mid-sentence.
    """
    text = raw.strip()
    if not text or BULLET_PREFIX.match(raw) or is_heading(raw):
        return False
    if _DATE.search(text) or _ENTRY_HEADER_HINT.search(text):
        return False
    previous_open = not previous.text.rstrip().endswith((".", "!", "?", ":", ";"))
    starts_mid_sentence = text[:1].islower()
    return previous_open or starts_mid_sentence


def _join_wrapped_lines(doc: ResumeDocument) -> None:
    """Fold wrapped fragments back into the bullet they belong to."""
    for section in doc.sections:
        merged: list[Line] = []
        for line in section.lines:
            if (
                merged
                and merged[-1].kind is LineKind.BULLET
                and line.kind is LineKind.FIXED
                and _looks_like_continuation(merged[-1], line.text)
            ):
                merged[-1].text = _stitch(merged[-1].text, line.text)
                continue
            merged.append(line)
        section.lines = merged


def _protect_skill_tables(doc: ResumeDocument) -> None:
    """Hold every line of a skills section immutable."""
    for section in doc.sections:
        if section.heading and _is_skills_heading(section.heading):
            for line in section.lines:
                line.kind = LineKind.FIXED


def _join_prose(doc: ResumeDocument) -> None:
    """Fold a wrapped summary paragraph into a single editable line."""
    for section in doc.sections:
        merged: list[Line] = []
        for line in section.lines:
            if merged and merged[-1].kind is LineKind.PROSE and line.kind is LineKind.PROSE:
                merged[-1].text = _stitch(merged[-1].text, line.text)
                continue
            merged.append(line)
        section.lines = merged


def _classify_prose(doc: ResumeDocument) -> None:
    """Mark summary prose editable; leave every other non-bullet line immutable.

    Only a section the CV already has can be edited this way. Nothing here creates a summary,
    and a CV without one simply has no editable prose — which is the correct outcome, not a
    gap to be filled.
    """
    for section in doc.sections:
        is_summary = not section.heading or bool(_SUMMARY_HEADING.search(section.heading))
        if not is_summary:
            continue
        for line in section.lines:
            if line.kind is LineKind.FIXED and not _is_contact_line(line.text):
                line.kind = LineKind.PROSE


def extract_from_pdf(path: str) -> ResumeDocument:
    """Parse a PDF CV, preferring the layout-aware extractor."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    return parse_resume_text(text, source_format="pdf")


def extract_from_docx(path: str) -> ResumeDocument:
    """Parse a DOCX CV.

    Table cells are read as well as paragraphs: CVs routinely lay the skills matrix out as a
    table, and reading paragraphs alone loses the entire section.
    """
    from docx import Document as DocxDocument

    document = DocxDocument(path)
    parts: list[str] = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return parse_resume_text("\n".join(parts), source_format="docx")
