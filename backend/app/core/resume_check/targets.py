"""What a target asks for: catalogue skills, each must-have or nice-to-have, with a weight.

Two targets share one shape:

* **A job** — skills the posting itself names. Must-have vs nice-to-have comes from where the
  posting says it: under a "Requirements / What you'll need" heading or on a "must / essential /
  required" line is a must-have; under "Nice to have / Desirable / Bonus" is not. A skill the
  posting never qualifies falls back to the role profile's flag for that title. When a posting
  is too thin to name six skills, the role profile for its title tops it up (and says so).
  A posting that never separates must-haves from extras gets every skill it names treated as a
  must-have — "nothing is required" would score any résumé as a perfect fit.
* **Skill Radar roles** — the merged demand of the selected role profiles (``aggregate``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.skills.aggregate import _present, aggregate
from app.core.skills.catalog import SKILLS, Skill
from app.core.skills.roles import skills_for_title

_MUST_HEAD = re.compile(
    r"requirement|essential|what you('ll| will)? (need|bring)|about you|you (will )?have|"
    r"must[- ]have|qualifications|skills (and|&) experience|who you are|what we('re| are) "
    r"looking for",
    re.I,
)
_NICE_HEAD = re.compile(r"nice[- ]to[- ]have|desirable|bonus|preferred|great if|plus\b", re.I)
_OTHER_HEAD = re.compile(
    r"responsibilit|what you('ll| will) do|the role|about (us|the)|benefits|perks|why join|"
    r"day[- ]to[- ]day|your impact",
    re.I,
)
_MUST_LINE = re.compile(r"\b(must|essential|required|minimum|proven|strong)\b", re.I)
_NICE_LINE = re.compile(
    r"\b(nice to have|desirable|bonus|preferred|ideally|a plus|advantageous)\b", re.I
)
MIN_POSTING_SKILLS = 6


@dataclass(frozen=True)
class TargetSkill:
    skill: Skill
    must_have: bool
    weight: int


@dataclass(frozen=True)
class Target:
    skills: list[TargetSkill]
    #: True when a thin posting was topped up from the role profile for its title.
    used_role_profile: bool = False


def _line_modes(description: str) -> list[tuple[str, str | None]]:
    """Each posting line with the mode its heading puts it in: "must", "nice" or None."""
    mode: str | None = None
    out: list[tuple[str, str | None]] = []
    for raw in (description or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        is_heading = len(line.split()) <= 8 and (line.endswith(":") or not line.endswith("."))
        if is_heading and _NICE_HEAD.search(line):
            mode = "nice"
        elif is_heading and _MUST_HEAD.search(line):
            mode = "must"
        elif is_heading and _OTHER_HEAD.search(line):
            mode = None
        out.append((line.lower(), mode))
    return out


def job_target(title: str, description: str) -> Target:
    profile = {key: (weight, must) for key, weight, must in skills_for_title(title or "")}
    lines = _line_modes(description)
    full = f"{title or ''}\n{description or ''}".lower()

    found: list[TargetSkill] = []
    for key, skill in SKILLS.items():
        if _present(skill, full) is None:
            continue
        verdicts = {_classify(line, mode) for line, mode in lines if _present(skill, line)}
        if "nice" in verdicts and "must" not in verdicts:
            must = False
        elif "must" in verdicts:
            must = True
        else:
            must = profile.get(key, (3, False))[1]
        weight = profile.get(key, (3, False))[0]
        found.append(TargetSkill(skill, must, weight + (1 if must else 0)))

    if found and not any(t.must_have for t in found):
        found = [TargetSkill(t.skill, True, t.weight + 1) for t in found]
    if len(found) >= MIN_POSTING_SKILLS:
        return Target(_ordered(found))
    have = {t.skill.key for t in found}
    topped = found + [
        TargetSkill(SKILLS[key], must, weight)
        for key, (weight, must) in profile.items()
        if key in SKILLS and key not in have
    ]
    return Target(_ordered(topped), used_role_profile=True)


def _classify(line: str, mode: str | None) -> str | None:
    if _NICE_LINE.search(line):
        return "nice"
    if mode is not None:
        return mode
    if _MUST_LINE.search(line):
        return "must"
    return None


def roles_target(titles: list[str]) -> Target:
    return Target(
        _ordered([TargetSkill(a.skill, a.must_have, a.demand) for a in aggregate(titles)])
    )


def _ordered(skills: list[TargetSkill]) -> list[TargetSkill]:
    return sorted(skills, key=lambda t: (not t.must_have, -t.weight, t.skill.label))
