"""Section-by-section review: summary, experience bullets, skills, formatting/ATS parsing risks.

Each review is deterministic, scored 0-1, and explains itself in findings a person can act on.
Thresholds are conventional UK recruiting guidance (a 2-4 line profile, outcome-led bullets,
a scannable skills block, 1-2 pages), not claims about any individual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.resume_check.targets import TargetSkill
from app.core.resume_check.text import Block, has_symbol_font_bullets
from app.core.skills.aggregate import _present

WEAK_OPENERS = (
    "responsible for",
    "worked on",
    "helped",
    "assisted",
    "involved in",
    "duties included",
    "tasked with",
    "participated in",
    "supported",
)
BUZZWORDS = (
    "hard-working",
    "hardworking",
    "team player",
    "results-driven",
    "detail-oriented",
    "go-getter",
    "self-starter",
    "passionate",
    "dynamic",
    "synergy",
)
_METRIC = re.compile(r"\d|%|£|\$|€|\bx\d|\bk\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(\+44|\b0)\s?\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}")
_FIRST_PERSON = re.compile(r"\b(i|my|me)\b", re.I)


@dataclass
class Review:
    key: str
    label: str
    status: str  # good | needs_work | missing
    score: float
    findings: list[str] = field(default_factory=list)
    weak_bullets: list[str] = field(default_factory=list)
    unquantified: list[str] = field(default_factory=list)


def _status(score: float) -> str:
    return "good" if score >= 0.75 else "needs_work"


def weak_opener(bullet: str) -> str | None:
    low = bullet.lower().lstrip()
    return next((w for w in WEAK_OPENERS if low.startswith(w)), None)


def review_summary(blocks: list[Block], target: list[TargetSkill], title: str) -> Review:
    paras = [b.text for b in blocks if b.section == "summary" and not b.is_bullet]
    if not paras:
        return Review(
            "summary",
            "Summary",
            "missing",
            0.0,
            [
                "No profile/summary found. Recruiters read the top third first; a 2-4 line "
                "summary naming the role you want and your strongest evidence frames everything "
                "below it."
            ],
        )
    text = " ".join(paras)
    words = len(text.split())
    score, findings = 1.0, []
    if words < 30:
        score -= 0.3
        findings.append(f"Summary is {words} words; 40-110 gives room for role, scope and proof.")
    elif words > 130:
        score -= 0.25
        findings.append(f"Summary is {words} words; trim to under ~110 so it is read, not skimmed.")
    else:
        findings.append(f"Summary length is {words} words — within the 40-110 range.")
    low = text.lower()
    musts = [t for t in target if t.must_have]
    named = [t.skill.label for t in musts if _present(t.skill, low)]
    if musts and len(named) < min(3, len(musts)):
        score -= 0.25
        findings.append(
            f"Names {len(named)} of the target's must-have skills; lead with the ones you can "
            "evidence below."
        )
    title_words = {w for w in re.findall(r"[a-z]{4,}", (title or "").lower())}
    if title_words and not any(w in low for w in title_words):
        score -= 0.15
        findings.append(f"Doesn't echo the target title ({title}); mirror it if it is accurate.")
    if len(_FIRST_PERSON.findall(text)) >= 2:
        score -= 0.1
        findings.append("Uses first person (I/my); UK CVs conventionally drop the pronoun.")
    buzz = [b for b in BUZZWORDS if b in low]
    if buzz:
        score -= 0.1
        findings.append(f"Generic phrases ({', '.join(buzz)}) add no evidence; replace with proof.")
    score = max(0.0, round(score, 4))
    return Review("summary", "Summary", _status(score), score, findings)


def review_experience(blocks: list[Block]) -> Review:
    bullets = [b.text for b in blocks if b.section == "experience" and b.is_bullet]
    if not bullets:
        bullets = [b.text for b in blocks if b.section == "experience" and len(b.text.split()) >= 8]
    if not bullets:
        return Review(
            "experience",
            "Experience bullets",
            "missing",
            0.0,
            [
                "No experience bullets found under an Experience heading. ATS parsers file "
                "everything by section; an unlabelled history may not be read as experience."
            ],
        )
    weak = [b for b in bullets if weak_opener(b)]
    unquantified = [b for b in bullets if not _METRIC.search(b)]
    long_ = [b for b in bullets if len(b.split()) > 45]
    metric_share = 1 - len(unquantified) / len(bullets)
    strong_share = 1 - len(weak) / len(bullets)
    score = round(0.55 * min(1.0, metric_share / 0.6) + 0.45 * strong_share, 4)
    findings = [
        f"{len(bullets)} bullets; {round(metric_share * 100)}% state a measurable outcome "
        "(aim for 60%+).",
    ]
    if weak:
        findings.append(
            f'{len(weak)} open with a duty ("{weak_opener(weak[0])}") rather than what you did.'
        )
    if long_:
        findings.append(f"{len(long_)} bullets run past 45 words; split or tighten them.")
    return Review(
        "experience",
        "Experience bullets",
        _status(score),
        score,
        findings,
        weak_bullets=weak,
        unquantified=[b for b in unquantified if b not in weak],
    )


def review_skills(blocks: list[Block], target: list[TargetSkill]) -> Review:
    skill_text = " ".join(b.text for b in blocks if b.section == "skills").lower()
    all_text = " ".join(b.text for b in blocks).lower()
    if not skill_text:
        return Review(
            "skills",
            "Skills",
            "missing",
            0.0,
            ["No Skills section. Many ATS filters match keywords against it first."],
        )
    in_section = [t for t in target if _present(t.skill, skill_text)]
    elsewhere = [
        t for t in target if not _present(t.skill, skill_text) and _present(t.skill, all_text)
    ]
    musts = [t for t in target if t.must_have]
    must_listed = [t for t in musts if _present(t.skill, skill_text)]
    score = round(len(must_listed) / len(musts), 4) if musts else 1.0
    findings = [f"Skills section names {len(in_section)} of {len(target)} target skills."]
    if elsewhere:
        labels = ", ".join(t.skill.label for t in elsewhere[:5])
        findings.append(f"Shown in your experience but not listed under Skills: {labels}.")
        score = max(0.0, round(score - 0.05 * min(len(elsewhere), 4), 4))
    return Review("skills", "Skills", _status(score), score, findings)


def review_formatting(raw_text: str, blocks: list[Block]) -> Review:
    findings: list[str] = []
    score = 1.0
    words = len((raw_text or "").split())
    if has_symbol_font_bullets(raw_text):
        score -= 0.25
        findings.append(
            "Bullets extract as unreadable symbol-font glyphs; use standard round bullets so "
            "ATS parsers don't treat them as text."
        )
    if not _EMAIL.search(raw_text or ""):
        score -= 0.25
        findings.append("No email address was found in the extracted text.")
    if not _PHONE.search(raw_text or ""):
        score -= 0.1
        findings.append("No UK phone number was found in the extracted text.")
    if words > 1100:
        score -= 0.15
        findings.append(f"{words} words — likely over two pages; recruiters skim past page two.")
    elif words < 250:
        score -= 0.15
        findings.append(f"Only {words} words were extracted — check the file isn't image-based.")
    sections = {b.section for b in blocks}
    for needed in ("experience", "education"):
        if needed not in sections:
            score -= 0.1
            findings.append(f"No recognisable {needed.title()} heading; use a standard one.")
    if not findings:
        findings.append("No parsing risks detected in the extracted text.")
    score = max(0.0, round(score, 4))
    return Review("formatting", "Formatting & ATS parsing", _status(score), score, findings)
