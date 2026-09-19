"""Bullet-quality check: does a résumé line read as Action Verb + Context + Metric?

A résumé bullet that just lists a duty ("Responsible for managing the local cloud
infrastructure") tells an ATS reviewer nothing a keyword scan wouldn't already know from the
job title. One that states an outcome with a number ("Cut cloud spend 22% by migrating to
spot instances") is what actually moves a human reviewer, and is exactly what the enterprise
ATS suites this product is trying to match (Workday, Taleo) weight bullet strength on. This
runs for free, on every score — no LLM call, no network — as a fast baseline the on-demand
LLM review (``services.resume_ats_review``) builds on rather than duplicates.
"""

from __future__ import annotations

import re

#: Openers that describe a duty rather than an outcome. Matched at the start of a bullet
#: (after stripping a leading bullet glyph/whitespace) — a passive verb mid-sentence is a
#: different, much noisier signal to chase, so this stays intentionally narrow.
_WEAK_OPENERS = (
    "responsible for", "duties included", "worked on", "worked with",
    "helped with", "helped to", "assisted with", "involved in",
    "participated in", "tasked with", "in charge of", "handled",
)

#: A bullet with any of these carries a quantifiable result — the thing weak bullets lack.
_METRIC_PATTERN = re.compile(r"\d|%|\$|£|€")

#: Bullets shorter than this are usually a section label or a stray fragment from PDF
#: extraction, not a real accomplishment line worth critiquing.
_MIN_BULLET_LEN = 15

#: Cap on how many entries feed a single suggestion — the point is "here's the pattern and
#: one fix to copy", not an exhaustive line-by-line edit list.
_MAX_EXAMPLES = 3


def _split_bullets(text: str) -> list[str]:
    if not text:
        return []
    # Résumé bullets arrive either as an actual list (parsed `responsibilities`) or as one
    # blob of `description` text — split the latter on common bullet/sentence boundaries.
    parts = re.split(r"[\n•·▪]+|(?<=[.;])\s+(?=[A-Z])", text)
    return [p.strip(" -\t") for p in parts if len(p.strip(" -\t")) >= _MIN_BULLET_LEN]


def _is_weak(bullet: str) -> bool:
    lower = bullet.lower().lstrip("-• \t")
    starts_weak = any(lower.startswith(opener) for opener in _WEAK_OPENERS)
    has_metric = bool(_METRIC_PATTERN.search(bullet))
    return starts_weak and not has_metric


def _format_suggestion(weak_examples: list[str]) -> list[str]:
    if not weak_examples:
        return []
    quoted = "; ".join(f'"{e}"' for e in weak_examples)
    return [
        f"{len(weak_examples)} bullet point(s) describe a duty with no measurable result — "
        f"{quoted}. Rewrite each as Action verb + what you did + a number: e.g. "
        '"Responsible for managing cloud infrastructure" -> '
        '"Cut cloud infrastructure spend 22% by migrating to spot instances."'
    ]


def check_bullet_impact_from_text(resume_text: str) -> list[str]:
    """Same check, run directly on raw résumé text — no structured profile required.

    ``check_bullet_impact`` below needs ``candidate_profile.experience`` entries, which only
    exist once the operator has a stored work history (Settings, or the LLM extraction flow).
    This variant is what the text-overlap fallback scorer uses instead: it has nothing but the
    résumé's raw text either way (no spaCy, no structured profile), and a weak bullet reads
    the same whether it came from a parsed entry or a raw line.
    """
    weak_examples: list[str] = []
    for bullet in _split_bullets(resume_text):
        if len(weak_examples) >= _MAX_EXAMPLES:
            break
        if _is_weak(bullet):
            weak_examples.append(bullet[:140])
    return _format_suggestion(weak_examples)


def check_bullet_impact(candidate_experience: list[dict]) -> list[str]:
    """Scan every experience entry's bullets; return 0-2 suggestions naming real examples.

    Returns an empty list rather than a generic "write stronger bullets" nag when nothing
    concrete was found to point at — a suggestion with no example is not actionable.
    """
    weak_examples: list[str] = []
    for entry in candidate_experience or []:
        if not isinstance(entry, dict):
            continue
        # A structured `responsibilities` entry is already one bullet (no splitting needed),
        # but it gets the same minimum-length filter as a `description` fragment — a stray
        # short entry ("Handled it") is a parsing artifact, not a real bullet to critique.
        raw_responsibilities = [str(r) for r in (entry.get("responsibilities") or [])]
        bullets = [r.strip(" -\t") for r in raw_responsibilities if len(r.strip(" -\t")) >= _MIN_BULLET_LEN]
        bullets += _split_bullets(str(entry.get("description") or ""))
        for bullet in bullets:
            if len(weak_examples) >= _MAX_EXAMPLES:
                break
            if _is_weak(bullet):
                weak_examples.append(bullet[:140])
        if len(weak_examples) >= _MAX_EXAMPLES:
            break

    return _format_suggestion(weak_examples)
