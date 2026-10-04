"""A résumé represented as the document it actually is, not as a fixed schema.

The engine this replaces flattened every CV into one hard-coded shape — name, summary,
skills, experience, education, certifications, projects — and recognised a section only when
its heading matched one of 24 exact strings. Run against a real CV whose headings read
"Key Highlights and Skills:", "EDUCATION & QUALIFICATIONS", "WORK & LEADERSHIP EXPERIENCE",
"EXTRA-CURRICULAR EXPERIENCE" and "CERTIFICATIONS & INTERESTS", all five missed, and 8,001
characters of career history reached the model as a name and an email address. Asked to
tailor that, the model invented a candidate.

So the model here keeps what the document says rather than what a schema expects:

* **Sections keep their own names and their own order.** No canonical vocabulary, no
  reordering, no renaming. A section called "WORK & LEADERSHIP EXPERIENCE" stays called that.
* **A section is an ordered list of lines**, each tagged as a bullet or not. Everything that
  is not a bullet — employer lines, role-and-dates lines, project sub-headings, the skills
  table — is immutable by construction: the editor has no operation that can touch it.
* **Bullets carry stable ids.** They are the only editable unit, which is what makes a
  minimum-diff edit expressible at all: an edit names a bullet id, and every bullet not named
  is kept verbatim.

Preserving employers, titles, dates, education and section order therefore is not a rule the
editor has to remember and a validator has to police. It is a property of the representation.
"""
# ruff: noqa: RUF001
# Bullet glyphs, en dashes and hyphen bullets appear as data here: these modules exist
# to recognise the characters real CVs are typeset with. ASCII look-alikes would stop
# them matching the documents they are written for.


from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum


class LineKind(StrEnum):
    """What a line is, which decides whether the editor may touch it."""

    #: A résumé bullet. The primary editable unit.
    BULLET = "bullet"
    #: Prose inside a summary-like section. Editable, because a professional summary is the
    #: one paragraph a tailored CV legitimately re-points at the target role — but only where
    #: the CV already has one. Nothing creates a summary that was not there.
    PROSE = "prose"
    #: An employer line, a role-and-dates line, a project sub-heading, a skills-table row, a
    #: heading. Immutable: the editor has no operation that can reach these.
    FIXED = "fixed"
    #: One "Label: item, item, item" row of a skills table. Editable under a stricter rule than a
    #: bullet: the label and every existing item stay in order, and items may only be appended.
    SKILL = "skill"


#: Bullet glyphs and list markers that real CVs use, in the order text extraction leaves them.
BULLET_PREFIX = re.compile(r"^\s*(?:[•●▪‣⁃·∙*\-–—]|\d{1,2}[.)])\s+")


def _strip_bullet(text: str) -> tuple[str, str]:
    """Split a line into its bullet marker and its content.

    The marker is kept so that rendering can put back exactly what was there rather than
    normalising every CV onto one glyph.
    """
    match = BULLET_PREFIX.match(text)
    if not match:
        return "", text.strip()
    return match.group(0), text[match.end():].strip()


@dataclass
class Style:
    """How one line is typeset in the source document.

    Carried on the line rather than decided by the renderer. A tailored CV that arrives in
    Calibri when the candidate wrote it in Times New Roman is not their CV, whatever the words
    say — and the renderer this replaces hard-coded its own font, size and colour, so every
    generated document looked like a different person's.

    Populated from the source where the format exposes it (PDF and DOCX both do). Left empty
    for plain text, where the renderer falls back to sensible defaults because there is
    genuinely nothing to preserve.
    """

    #: Typeface name as the source names it, e.g. "Times New Roman".
    font: str = ""
    #: Point size.
    size: float = 0.0
    bold: bool = False
    italic: bool = False
    #: RGB as three 0-255 ints. ``None`` means the source used the default text colour.
    colour: tuple[int, int, int] | None = None
    #: "left" | "center" | "right"; inferred from the line's position on the page.
    align: str = "left"
    #: Vertical gap above this line in points, so section breathing room survives.
    space_before: float = 0.0

    @property
    def defined(self) -> bool:
        return bool(self.font or self.size)


@dataclass
class Line:
    """One line of the document, in its original order."""

    #: Stable within a document; assigned at parse time and never reused.
    id: str
    kind: LineKind
    #: The content, with any bullet marker removed. This is what an edit replaces.
    text: str
    #: The marker that introduced this line, restored verbatim on render.
    marker: str = ""
    #: Leading whitespace, which carries nesting in many CVs.
    indent: str = ""
    #: Typography copied from the source, so the output is the same document.
    style: Style = field(default_factory=Style)

    @property
    def editable(self) -> bool:
        return self.kind in (LineKind.BULLET, LineKind.PROSE, LineKind.SKILL)

    def rendered(self) -> str:
        """The line as it should appear in the output document."""
        return f"{self.indent}{self.marker}{self.text}"


@dataclass
class Section:
    """A named run of lines, in the order and under the name the CV used."""

    #: Verbatim heading text, e.g. "WORK & LEADERSHIP EXPERIENCE". Empty for the block of
    #: content that appears before any heading — a summary paragraph with no heading of its
    #: own is extremely common and was silently discarded by the previous parser.
    heading: str
    #: Position in the original document. Preserved on output; never sorted.
    order: int
    #: Typography of the heading itself, which is usually the most distinctive styling in a
    #: CV — the teal 12pt bold that makes it look like this person's document.
    heading_style: Style = field(default_factory=Style)
    lines: list[Line] = field(default_factory=list)

    @property
    def bullets(self) -> list[Line]:
        return [ln for ln in self.lines if ln.kind is LineKind.BULLET]

    @property
    def editable_lines(self) -> list[Line]:
        return [ln for ln in self.lines if ln.editable]

    def word_count(self) -> int:
        return sum(len(ln.text.split()) for ln in self.lines)


@dataclass
class ResumeDocument:
    """A parsed CV: contact details, then sections in document order."""

    #: The first lines of the CV, before any section — name and contact details. Immutable.
    header: list[Line] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    #: Where this came from, so the renderer can prefer the original file as a base.
    source_format: str = ""
    #: (left, right, top, bottom) in points, measured from the source's own text block.
    #: Word's one-inch default would reflow a CV that was fitted to three pages onto four.
    page_margins: tuple[float, float, float, float] | None = None
    #: line id -> where that line sits on the source PDF page (``pdf_layout.PParagraph``).
    #: Present only for documents read from a PDF; it is what lets an edit be written back
    #: into the original file instead of rebuilding the document from text.
    layout: dict[str, object] = field(default_factory=dict)
    #: line id -> roughly how many characters fit where the line sits (PDF sources only).
    capacity: dict[str, int] = field(default_factory=dict)

    # -- read-only views ---------------------------------------------------------------

    def all_lines(self) -> list[Line]:
        out = list(self.header)
        for section in self.sections:
            out.extend(section.lines)
        return out

    def bullets(self) -> list[Line]:
        """Every editable line: bullets plus any summary prose."""
        return [ln for ln in self.all_lines() if ln.editable]

    def bullet_by_id(self, bullet_id: str) -> Line | None:
        return next((ln for ln in self.bullets() if ln.id == bullet_id), None)

    def section_of(self, bullet_id: str) -> Section | None:
        for section in self.sections:
            if any(ln.id == bullet_id for ln in section.lines):
                return section
        return None

    def headings(self) -> list[str]:
        return [s.heading for s in self.sections if s.heading]

    def word_count(self) -> int:
        return sum(len(ln.text.split()) for ln in self.all_lines())

    def to_text(self) -> str:
        """The document as plain text, in original order.

        Round-tripping through this is how the validator checks that an edit changed only
        what it claimed to change.
        """
        parts = [ln.rendered() for ln in self.header]
        for section in self.sections:
            if section.heading:
                parts.append("")
                parts.append(section.heading)
            parts.extend(ln.rendered() for ln in section.lines)
        return "\n".join(parts).strip()

    def fingerprint(self) -> str:
        """Hash of every immutable line.

        Compared before and after editing: if this changes, something the editor was never
        allowed to touch has moved, and the result is rejected rather than shipped.
        """
        fixed = [ln.text for ln in self.all_lines() if not ln.editable]
        # A skills row's label is as fixed as any heading; only its list of items may grow.
        fixed.extend(ln.text.split(":", 1)[0] for ln in self.all_lines() if ln.kind is LineKind.SKILL)
        fixed.extend(s.heading for s in self.sections)
        return hashlib.sha256("\u0000".join(fixed).encode()).hexdigest()

    def copy(self) -> ResumeDocument:
        """A deep copy, so an edit plan can be applied without mutating the original."""
        return ResumeDocument(
            header=[
                Line(ln.id, ln.kind, ln.text, ln.marker, ln.indent, ln.style)
                for ln in self.header
            ],
            sections=[
                Section(
                    heading=s.heading,
                    order=s.order,
                    heading_style=s.heading_style,
                    lines=[
                        Line(ln.id, ln.kind, ln.text, ln.marker, ln.indent, ln.style)
                        for ln in s.lines
                    ],
                )
                for s in self.sections
            ],
            source_format=self.source_format,
            page_margins=self.page_margins,
            layout=self.layout,
            capacity=self.capacity,
        )


def make_line(index: int, raw: str) -> Line:
    """Build a :class:`Line` from one raw line of extracted text."""
    indent = raw[: len(raw) - len(raw.lstrip())]
    marker, text = _strip_bullet(raw)
    kind = LineKind.BULLET if marker else LineKind.FIXED
    return Line(id=f"L{index:04d}", kind=kind, text=text, marker=marker, indent=indent)
