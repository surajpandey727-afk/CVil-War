"""Shorten bullets, and only shorten them, so a section can fit the page it must fit on.

The owner's rule is that Education and Work sit on one page. When they do not, the first remedy is
better writing: the same facts in fewer words. This module asks for exactly that and accepts
nothing else: a condensed line may only *remove* words. It cannot add one, change a figure, or
drop a term the job posting asked for. Anything else is rejected, so condensing can free space but
can never change what the résumé claims.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import structlog

from app.core.llm.prompts.standing import RESUME_GENERATION_STANDARD, with_standing
from app.core.resume_tailoring.plan import BANNED_PHRASES, EditPlan
from app.core.resume_tailoring.validate import _numbers, _tokens

logger = structlog.get_logger(__name__)

_SYSTEM = """\
You condense résumé bullets. You are not rewriting them: you remove words so a bullet takes fewer \
lines, keeping every fact. For each bullet you are told, return the same sentence with less \
wording.

Hard rules, each checked by code, and a bullet that breaks one is discarded:
  * Use only words already in that bullet. Do not add, substitute or re-order for style.
  * Keep every number, percentage, name, technology and product exactly as written.
  * Keep every term listed under PROTECTED TERMS that the bullet contains.
  * The result must be a complete, natural sentence, shorter than the original, with no fragments.
  * Remove filler first (adverbs, "in order to", "a variety of", repeated qualifiers). Never \
remove an accomplishment or its measured result.

Return ONLY valid JSON matching the schema; put the shortened sentence in after_text and a short \
reason (which words you removed). Leave a bullet out if it cannot be shortened without \nlosing a fact."""


@dataclass
class CondenseTarget:
    """A bullet that might give up a line, and what it would take."""

    line_id: str
    text: str
    lines: int
    #: Characters on its last line: dropping that many (and a little more) saves the line.
    last_line_chars: int


def render_prompt(
    targets: list[CondenseTarget], lines_needed: int, protected: Iterable[str]
) -> str:
    rows = [
        {
            "line_id": t.line_id,
            "text": t.text,
            "lines_now": t.lines,
            "remove_at_least_chars_to_save_a_line": t.last_line_chars + 2,
        }
        for t in targets
    ]
    import json

    return (
        f"The page is {lines_needed} line(s) too full. Shorten bullets below, saving at least "
        f"{lines_needed} line(s) in total. A bullet saves a line only if enough characters are "
        "removed (see remove_at_least_chars_to_save_a_line); prefer the bullets where that is "
        "smallest. Do not touch bullets you do not need to.\n\n"
        f"PROTECTED TERMS (keep when present): {json.dumps(sorted(set(protected)))}\n\n"
        f"BULLETS:\n{json.dumps(rows, indent=2)}\n\n"
        'For each bullet you shorten return: line_id, action ("tweak"), after_text (the complete '
        "shortened sentence), reason, evidence (the original text), keywords_added ([]) and level "
        '("1_clarity").'
    )


def check(old: str, new: str, protected: Iterable[str]) -> str | None:
    """Why ``new`` is not an acceptable condensing of ``old``, or None if it is."""
    new, old = new.strip(), old.strip()
    if not new or new == old:
        return "unchanged"
    if len(new) >= len(old):
        return "not shorter"
    extra = _tokens(new) - _tokens(old)
    if extra:
        return f"adds words: {', '.join(sorted(extra)[:4])}"
    if _numbers(new) != _numbers(old):
        return "changes a figure"
    low_new = new.lower()
    for term in protected:
        if term.lower() in old.lower() and term.lower() not in low_new:
            return f"drops the protected term '{term}'"
    if any(p in low_new and p not in old.lower() for p in BANNED_PHRASES):
        return "introduces machine-sounding wording"
    if not re.search(r"[A-Za-z]{3}", new) or len(new.split()) < max(4, len(old.split()) // 3):
        return "too truncated to be a sentence"
    return None


async def propose(
    llm: Any, targets: list[CondenseTarget], lines_needed: int, protected: Iterable[str]
) -> dict[str, str]:
    """Condensed text per line id: only edits that pass :func:`check`."""
    if llm is None or not targets:
        return {}
    protected = list(protected)
    try:
        plan = await asyncio.wait_for(
            llm.complete_with_structured_output(
                prompt=render_prompt(targets, lines_needed, protected),
                output_schema=EditPlan,
                system_prompt=with_standing(_SYSTEM, RESUME_GENERATION_STANDARD),
                purpose="resume_condense_to_fit",
                temperature=0.1,
            ),
            timeout=90,
        )
    except Exception:
        logger.exception("resume_condense_failed")
        return {}
    by_id = {t.line_id: t for t in targets}
    out: dict[str, str] = {}
    for edit in plan.edits:
        target = by_id.get(edit.line_id)
        if target is None or edit.line_id in out:
            continue
        problem = check(target.text, edit.after_text, protected)
        if problem:
            logger.info("condense_rejected", line_id=edit.line_id, why=problem)
            continue
        out[edit.line_id] = edit.after_text.strip()
    return out
