"""Turn extracted résumé text into sectioned blocks, and quote evidence from it.

Extracted PDF text arrives hard-wrapped (~100 chars a line), so one bullet or one summary
paragraph spans several lines. Everything downstream — evidence quotes, bullet review, the
LLM's "original" check — works on re-joined *blocks*: a bullet with its continuation lines, or
a paragraph. Quotes are always verbatim substrings of a block, never paraphrased.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.ats_engine.structure import section_kind
from app.core.skills.aggregate import _present
from app.core.skills.catalog import Skill

#: Bullet glyphs, including the Private Use Area code points a Symbol-font bullet decodes to
#: (U+F0B7, U+F0A7, ...) — these survive extraction as junk and are an ATS parsing risk.
BULLET_CHARS = "*-" + "".join(
    chr(c)
    for c in (
        0x2022, 0x25CF, 0x25AA, 0x25E6, 0x2023, 0x2219, 0x00B7,  # round/square/dot bullets
        0x2013, 0x2014,  # en/em dash used as a bullet
        0xF0B7, 0xF0A7, 0xF076, 0xF0D8, 0xF0FC, 0xFFFD,  # Symbol/Wingdings PUA + replacement
    )
)  # fmt: skip
_BULLET_RE = re.compile(rf"^\s*[{re.escape(BULLET_CHARS)}]\s+")
_PUA_RE = re.compile(r"[-�]")
_HEADING_MAX_WORDS = 5


@dataclass(frozen=True)
class Block:
    section: str  # summary | experience | skills | education | certifications | projects | other
    text: str
    is_bullet: bool


def _is_heading(line: str) -> str | None:
    """Section kind if ``line`` reads as a section heading, else ``None``."""
    stripped = line.strip().rstrip(":").strip()
    if not stripped or _BULLET_RE.match(line) or len(stripped.split()) > _HEADING_MAX_WORDS:
        return None
    if stripped.endswith(".") or any(ch.isdigit() for ch in stripped):
        return None
    # "SimplyPhi, Woking, UK, (Technology Team)" is an employer line, not a Skills heading,
    # however much "Technology" looks like one. Real headings carry no commas or brackets.
    if any(ch in stripped for ch in ",()"):
        return None
    kind = section_kind(stripped)
    if kind != "other":
        return kind
    if stripped.isupper() and len(stripped) > 3:
        return "other"
    return None


def clean(text: str) -> str:
    """Strip bullet glyphs and collapse whitespace — the form a quote is compared in."""
    return re.sub(r"\s+", " ", _BULLET_RE.sub("", text)).strip()


def split_blocks(text: str) -> list[Block]:
    """Group résumé lines into bullets and paragraphs, each tagged with its section.

    Text before the first recognised heading is the header (name/contact) and, when it reads as
    prose, an implicit summary.
    """
    blocks: list[Block] = []
    section = "header"
    current: list[str] = []
    current_bullet = False

    def flush() -> None:
        nonlocal current
        if current:
            joined = clean(" ".join(current))
            if joined:
                blocks.append(Block(section, joined, current_bullet))
        current = []

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        kind = _is_heading(line)
        if kind is not None:
            flush()
            section = kind
            continue
        if _BULLET_RE.match(line):
            flush()
            current, current_bullet = [line], True
            continue
        if current and (current_bullet or not _looks_like_new_item(line)):
            current.append(line)
        else:
            flush()
            current, current_bullet = [line], False
    flush()
    return [_promote_header_summary(b) for b in blocks]


def _looks_like_new_item(line: str) -> bool:
    """A short line, or one starting a date/role, begins a new block rather than continuing."""
    s = line.strip()
    return len(s) < 45 or bool(re.match(r"^(19|20)\d{2}\b", s))


def _promote_header_summary(block: Block) -> Block:
    if block.section == "header" and not block.is_bullet and len(block.text.split()) >= 25:
        return Block("summary", block.text, False)
    return block


def has_symbol_font_bullets(text: str) -> bool:
    return bool(_PUA_RE.search(text or ""))


def find_evidence(skill: Skill, blocks: list[Block], limit: int = 2) -> list[tuple[str, str]]:
    """Up to ``limit`` verbatim quotes showing ``skill``, experience before skills lists.

    A quote is the sentence containing the match, trimmed to ~220 chars around it, so a long
    bullet still yields a readable, verbatim excerpt.
    """
    order = {"experience": 0, "projects": 1, "summary": 2, "skills": 3}
    hits: list[tuple[int, str, str]] = []
    for block in blocks:
        low = block.text.lower()
        form = _present(skill, low)
        if form is None:
            continue
        hits.append((order.get(block.section, 4), _excerpt(block.text, form), block.section))
    hits.sort(key=lambda h: h[0])
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for _, quote, section in hits:
        if quote in seen:
            continue
        seen.add(quote)
        out.append((quote, section))
        if len(out) == limit:
            break
    return out


def _excerpt(text: str, form: str, width: int = 220) -> str:
    sentences = re.split(r"(?<=[.;!?])\s+", text)
    for sentence in sentences:
        if form.lower() in sentence.lower():
            text = sentence
            break
    if len(text) <= width:
        return text
    at = max(0, text.lower().find(form.lower()))
    start = max(0, at - width // 2)
    end = min(len(text), start + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def contains_verbatim(haystack: str, needle: str) -> bool:
    """Whitespace/case-insensitive containment, ignoring bullet glyphs and trailing punctuation."""
    norm = lambda s: re.sub(r"\s+", " ", clean(s)).lower().strip(" .;,")  # noqa: E731
    n = norm(needle)
    return bool(n) and n in norm(haystack)
