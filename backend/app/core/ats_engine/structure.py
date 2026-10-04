"""Read a parsed résumé as an evaluator would: sections, roles, dates, impact (brief sections 9–13).

Turns a :class:`ResumeDocument` into flat "units" (one per line of content), each knowing which
section it is in, which role, how recent that role was, and whether the line shows a result. The
matching and scoring layers work from this view, so none of them re-derives structure on its own.
"""
# ruff: noqa: RUF001, RUF002, E501
# Date separators include en/em dashes; the action-verb regex is one pattern.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.core.resume_tailoring.model import LineKind, ResumeDocument

_SECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "other",
        re.compile(
            r"extra[- ]?curricular|volunteer|interests|hobbies|awards?|publications?|references",
            re.I,
        ),
    ),
    ("summary", re.compile(r"summary|profile|about me|objective|overview", re.I)),
    ("education", re.compile(r"educat|academic|qualification", re.I)),
    ("certifications", re.compile(r"certif|licen[cs]e|courses?|training", re.I)),
    ("skills", re.compile(r"skills?|technolog|competenc|tools|expertise|toolkit", re.I)),
    ("projects", re.compile(r"projects?", re.I)),
    ("experience", re.compile(r"experience|employment|work history|career|positions?", re.I)),
)
_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
]
_MONTH_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = rf"(?:{_MONTH_RE}\s+)?(?:19|20)\d{{2}}|\d{{1,2}}/(?:19|20)\d{{2}}"
_RANGE = re.compile(
    rf"({_DATE})\s*(?:-|–|—|to)\s*({_DATE}|present|current|now|ongoing|today)", re.I
)
_YEAR_ONLY = re.compile(r"\b((?:19|20)\d{2})\b")
_NUMBER = re.compile(
    r"(?:\$|£|€)\s?\d|\b\d[\d,.]*\s?(?:%|x\b|k\b|m\b|bn\b|million|billion|thousand)|\b\d{2,}\b"
)
_ACTION = re.compile(
    r"^(?:\W*)(built|led|designed|developed|launched|delivered|owned|drove|managed|created|defined|"
    r"implemented|deployed|reduced|increased|improved|shipped|scaled|automated|analy[sz]ed|established|"
    r"introduced|streamlined|negotiated|mentored|coordinated|architected|spearheaded|orchestrated|"
    r"productioni[sz]ed|optimi[sz]ed|migrated|integrated|partnered|translated|transformed|produced|"
    r"conducted|presented|authored|wrote|ran|set up|oversaw|directed|executed|piloted|prioriti[sz]ed)\b",
    re.I,
)
_RESULT_WORDS = re.compile(
    r"\b(reduc|increas|improv|saving|saved|grew|growth|boost|cut|lift|faster|revenue|cost|accuracy|adoption|retention)",
    re.I,
)
_LEADERSHIP = re.compile(
    r"\b(led|lead|leading|managed|mentored|owned|ownership|directed|head|oversaw|accountable|strategy|roadmap|executive|c-suite|stakeholders?)\b",
    re.I,
)


def section_kind(heading: str) -> str:
    for kind, pattern in _SECTION_RULES:
        if pattern.search(heading or ""):
            return kind
    return "other"


def _parse_date(token: str, *, end: bool) -> tuple[int, int] | None:
    low = token.lower().strip()
    if re.fullmatch(r"present|current|now|ongoing|today", low):
        today = date.today()
        return today.year, today.month
    year = _YEAR_ONLY.search(low)
    if not year:
        return None
    month = 12 if end else 1
    named = re.search(_MONTH_RE, low)
    if named:
        month = (
            _MONTHS.index(named.group(0)[:3].lower().replace("sept", "sep")) + 1
            if named.group(0)[:3].lower() in _MONTHS
            else month
        )
    else:
        slash = re.match(r"(\d{1,2})/", low)
        if slash:
            month = max(1, min(12, int(slash.group(1))))
    return int(year.group(1)), month


def date_range(text: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    match = _RANGE.search(text)
    if match:
        start, stop = _parse_date(match.group(1), end=False), _parse_date(match.group(2), end=True)
        if start and stop:
            return start, stop
    years = _YEAR_ONLY.findall(text)
    if len(years) >= 2 and re.search(r"[-–—]", text):
        return (int(years[0]), 1), (int(years[1]), 12)
    return None


@dataclass
class Unit:
    """One line of résumé content and where it sits."""

    line_id: str
    text: str
    #: header | summary | experience | education | skills | certifications | projects | other
    section: str
    kind: LineKind
    role: int | None = None  # index of the role within experience-like sections
    position: int = 0  # bullet position within its role
    recency: float = 0.5
    #: A fixed-kind line that is nonetheless a sentence of work (a demoted sub-bullet).
    content: bool = False
    #: Set by the matcher when the line merely lists requirement terms rather than describing work.
    stuffed: bool = False
    quantified: bool = False
    action: bool = False
    result: bool = False

    @property
    def lower(self) -> str:
        return self.text.lower()

    @property
    def is_evidence(self) -> bool:
        """A line that can show work was done: a bullet or prose in experience or projects."""
        return (
            self.section in ("experience", "projects")
            and not self.stuffed
            and (self.kind in (LineKind.BULLET, LineKind.PROSE) or self.content)
        )


@dataclass
class Role:
    index: int
    heading: str = ""
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None

    @property
    def months(self) -> int:
        if not (self.start and self.end):
            return 0
        return max(0, (self.end[0] - self.start[0]) * 12 + self.end[1] - self.start[1] + 1)


@dataclass
class Structure:
    units: list[Unit] = field(default_factory=list)
    roles: list[Role] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    section_kinds: list[str] = field(default_factory=list)
    stated_years: int | None = None

    def of(self, *sections: str) -> list[Unit]:
        return [u for u in self.units if u.section in sections]

    @property
    def evidence(self) -> list[Unit]:
        return [u for u in self.units if u.is_evidence]

    @property
    def total_years(self) -> float:
        """Years of experience covered by the dated roles, overlaps counted once."""
        spans = sorted(
            (r.start[0] * 12 + r.start[1], r.end[0] * 12 + r.end[1])
            for r in self.roles
            if r.start and r.end
        )
        covered, cursor = 0, None
        for lo, hi in spans:
            if cursor is None or lo > cursor:
                covered += hi - lo + 1
                cursor = hi
            elif hi > cursor:
                covered += hi - cursor
                cursor = hi
        return covered / 12.0

    @property
    def top_zone(self) -> list[Unit]:
        """The part a reader sees first: header, summary, skills and the first role's lead "
        "bullets."""
        zone = self.of("header", "summary", "skills")
        first = next((r.index for r in self.roles), None)
        zone += [
            u
            for u in self.units
            if u.section == "experience" and u.role == first and u.position < 5
        ]
        return zone


def _recency(end: tuple[int, int] | None, rank: int) -> float:
    if end is None:
        return max(0.45, 1.0 - 0.18 * rank)
    today = date.today()
    ago = max(0.0, ((today.year - end[0]) * 12 + today.month - end[1]) / 12.0)
    return (
        1.0 if ago <= 1 else 0.9 if ago <= 3 else 0.75 if ago <= 6 else 0.6 if ago <= 10 else 0.45
    )


def _sentence_like(text: str) -> bool:
    """A line that describes work, as opposed to a company, title, date or project name."""
    words = text.split()
    return len(words) >= 11 or (len(words) >= 7 and text.rstrip().endswith("."))


def _role_starts(lines: list) -> dict[int, int]:
    """Map the index of each role's first heading line to the index of its dated line.

    A role is anchored by the line holding its date range; the one or two short fixed lines
    just above it (employer, title) belong to the same role. Project names and sub-bullets
    between roles are left with the role they follow.
    """
    anchors = [
        i
        for i, ln in enumerate(lines)
        if ln.kind is LineKind.FIXED and not _sentence_like(ln.text) and date_range(ln.text)
    ]
    starts: dict[int, int] = {}
    for i in anchors:
        first = i
        while first - 1 >= 0 and i - (first - 1) <= 2:
            prev = lines[first - 1]
            if (
                prev.kind is not LineKind.FIXED
                or _sentence_like(prev.text)
                or date_range(prev.text)
                or (first - 1) in starts
            ):
                break
            first -= 1
        starts[first] = i
    return starts


def analyse(doc: ResumeDocument) -> Structure:
    """The structured view of ``doc``."""
    out = Structure()
    for line in doc.header:
        out.units.append(Unit(line.id, line.text, "header", line.kind))
    role_count = 0
    for sec in doc.sections:
        kind = section_kind(sec.heading) if sec.heading else "summary"
        out.headings.append(sec.heading)
        out.section_kinds.append(kind)
        starts = _role_starts(sec.lines) if kind == "experience" else {}
        heading_lines = {i for first, dated in starts.items() for i in range(first, dated + 1)}
        current: Role | None = None
        position = 0
        for index, line in enumerate(sec.lines):
            unit = Unit(line.id, line.text, kind, line.kind)
            if kind == "experience":
                if index in starts:
                    current = Role(role_count)
                    out.roles.append(current)
                    role_count += 1
                    position = 0
                    span = date_range(sec.lines[starts[index]].text)
                    if span:
                        current.start, current.end = span
                if index in heading_lines and current is not None:
                    current.heading = (current.heading + " " + line.text).strip()
                elif line.kind is LineKind.FIXED and _sentence_like(line.text):
                    unit.content = True
                unit.role = current.index if current else None
                if unit.is_evidence:
                    unit.position = position
                    position += 1
            body = line.text
            unit.quantified = bool(_NUMBER.search(body))
            unit.action = bool(_ACTION.search(body))
            unit.result = bool(_RESULT_WORDS.search(body)) and unit.quantified
            out.units.append(unit)
    ranks = {r.index: n for n, r in enumerate(out.roles)}
    by_role = {r.index: _recency(r.end, ranks[r.index]) for r in out.roles}
    for unit in out.units:
        if unit.role is not None:
            unit.recency = by_role.get(unit.role, 0.5)
    stated = [
        int(m)
        for m in re.findall(r"(\d{1,2})\s*\+?\s*years?", " ".join(u.text for u in out.units), re.I)
    ]
    out.stated_years = max(stated) if stated else None
    return out


def leadership_signals(structure: Structure) -> int:
    return sum(1 for u in structure.evidence if _LEADERSHIP.search(u.text))
