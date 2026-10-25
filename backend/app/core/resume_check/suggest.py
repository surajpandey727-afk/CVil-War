"""Rewrite suggestions under the owner's experience policy.

The policy: never invent employers, credentials or metrics. A suggestion may *propose* content
the résumé does not show — a missing skill, a number for a bullet — but then it is marked
``add_only_if_true`` so it can never be mistaken for a fact. :func:`evidence_status` is the one
place that decision is made, for rule-based and Claude-written suggestions alike.
"""

from __future__ import annotations

import re

from app.core.resume_check.sections import Review, weak_opener
from app.core.resume_check.targets import TargetSkill
from app.core.skills.aggregate import _present
from app.core.skills.catalog import SKILLS
from app.schemas.resume_check import Suggestion

_NUMBER = re.compile(r"\d[\d,.]*")
_PLACEHOLDER = re.compile(r"\[[^\]]+\]")
_CREDENTIAL = re.compile(
    r"\b(certified|certification|certificate|degree|bsc|msc|mba|phd|chartered|accredited|"
    r"licen[cs]ed)\b",
    re.I,
)
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-zA-Z0-9&]+(?:\s+[A-Z][a-zA-Z0-9&]+)*)")
#: Capitalised words that are ordinary sentence furniture, not claims.
_COMMON_CAPS = {"I", "UK", "AI", "ML", "KPI", "KPIs", "OKR", "OKRs", "API", "APIs", "SQL"}


def _unsupported(suggested: str, resume_low: str) -> list[str]:
    """Everything in ``suggested`` the résumé does not already evidence."""
    body = _PLACEHOLDER.sub(" ", suggested)
    problems: list[str] = []
    if _PLACEHOLDER.search(suggested):
        problems.append("placeholder to fill in")
    for num in _NUMBER.findall(body):
        if num.strip(".,") and num.strip(".,") not in resume_low:
            problems.append(f"number {num}")
    for match in _CREDENTIAL.finditer(body):
        if match.group(0).lower() not in resume_low:
            problems.append(f"credential '{match.group(0)}'")
    for skill in SKILLS.values():
        if _present(skill, body.lower()) and not _present(skill, resume_low):
            problems.append(f"skill '{skill.label}'")
    for name in _PROPER.findall(body):
        if name in _COMMON_CAPS or name.lower() in resume_low:
            continue
        problems.append(f"name '{name}'")
    return problems


def evidence_status(suggested: str, resume_text: str) -> str:
    return "add_only_if_true" if _unsupported(suggested, resume_text.lower()) else "supported"


def rule_suggestions(
    *,
    resume_text: str,
    target: list[TargetSkill],
    missing_ranked: list[TargetSkill],
    demand: dict[str, int],
    scanned: int,
    reviews: dict[str, Review],
    skills_text: str,
) -> list[Suggestion]:
    out: list[Suggestion] = []
    low = resume_text.lower()

    for t in [m for m in missing_ranked if m.must_have][:4]:
        asked = (
            f"asked for in {demand.get(t.skill.key, 0)} of {scanned} UK jobs scanned"
            if scanned
            else "a must-have for this target"
        )
        out.append(
            Suggestion(
                section="skills",
                kind="add",
                suggested=f'Add "{t.skill.label}" to Skills and name one place you used it.',
                reason=f"Must-have you don't show yet; {asked}.",
                evidence_status="add_only_if_true",
            )
        )

    # A target skill the experience already proves, missing only from the Skills list, is a
    # supported addition — nothing new is being claimed.
    skills_low = skills_text.lower()
    if skills_low:
        unlisted = [
            t for t in target if _present(t.skill, low) and not _present(t.skill, skills_low)
        ]
        for t in unlisted[:3]:
            out.append(
                Suggestion(
                    section="skills",
                    kind="add",
                    suggested=f'List "{t.skill.label}" under Skills.',
                    reason="Your experience already shows it; ATS filters often match the "
                    "Skills section first.",
                    evidence_status="supported",
                )
            )

    summary = reviews.get("summary")
    if summary and summary.status == "missing":
        shown = [t.skill.label for t in target if t.must_have and _present(t.skill, low)][:3]
        if shown:
            text = (
                "Add a 2-3 line summary: the role you're targeting, then your strongest "
                f"evidenced skills — {', '.join(shown)}."
            )
            out.append(
                Suggestion(
                    section="summary",
                    kind="add",
                    suggested=text,
                    reason="No summary found; these skills are already evidenced below it.",
                    evidence_status="supported",
                )
            )

    exp = reviews.get("experience")
    if exp:
        for bullet in exp.weak_bullets[:3]:
            opener = weak_opener(bullet) or ""
            rest = bullet[len(opener) :].strip(" :,-") if opener else bullet
            # The verb is the candidate's to choose: we know the duty, not what they did.
            suggested = (
                f"[What you did, e.g. Redesigned] {rest[:1].lower()}{rest[1:].rstrip('.')}"
                " — resulting in [outcome]."
            )
            out.append(
                Suggestion(
                    section="experience",
                    kind="rewrite",
                    original=bullet,
                    suggested=suggested,
                    reason=(
                        f'Opens with a duty ("{opener}"). Lead with what you did, then the '
                        "result — fill [outcome] only with something true."
                    ),
                    evidence_status="add_only_if_true",
                )
            )
        for bullet in exp.unquantified[:2]:
            out.append(
                Suggestion(
                    section="experience",
                    kind="rewrite",
                    original=bullet,
                    suggested=f"{bullet.rstrip('.')} — [scale or result: users, £, %, time saved].",
                    reason="States the work but not its size or effect; add a real figure if "
                    "you have one.",
                    evidence_status="add_only_if_true",
                )
            )
    return out
