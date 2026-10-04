"""Trusted career evidence beyond the PDF being edited.

A CV is a selection: facts are left out for space or because an earlier target did not need
them. "Not in this PDF" therefore does not mean "never done". The tailoring pass may surface a
fact the PDF omitted — but only one a trusted source states, and the change log must say which.

Two sources exist in the product today and both are the candidate's own words:

* the structured candidate profile (Settings) — work history, skills and education the
  candidate or the résumé reader recorded;
* the candidate's other base résumés — previous versions that carry facts this one dropped.

Résumés *generated* by tailoring are never used: they derive from the base, so quoting one as
evidence would let a past edit vouch for itself.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

#: Evidence text is capped per source so a long history cannot swamp the prompt.
_MAX_SOURCE_CHARS = 9000


@dataclass(frozen=True)
class TrustedSource:
    """One body of trusted text and a label a reader can recognise it by."""

    label: str
    text: str


def _flatten(value: object) -> list[str]:
    """Every string inside a nested profile, one per line, in order."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        return [line for v in value.values() for line in _flatten(v)]
    if isinstance(value, (list, tuple)):
        return [line for v in value for line in _flatten(v)]
    return []


def profile_source(profile: dict | None) -> TrustedSource | None:
    """The structured candidate profile as a source, or ``None`` if it holds nothing."""
    if not isinstance(profile, dict):
        return None
    text = "\n".join(_flatten(profile))[:_MAX_SOURCE_CHARS]
    return TrustedSource("Career profile (Settings)", text) if text.strip() else None


def resume_source(name: str, text: str | None) -> TrustedSource | None:
    cleaned = (text or "").strip()
    return TrustedSource(f"Previous résumé: {name}", cleaned[:_MAX_SOURCE_CHARS]) if cleaned else None


def evidence_text(sources: Iterable[TrustedSource]) -> str:
    return "\n".join(s.text for s in sources)


def _present(term: str, haystack: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(term.lower())}(?![A-Za-z0-9])", haystack))


def sources_containing(terms: Iterable[str], sources: Iterable[TrustedSource]) -> list[str]:
    """Labels of the sources that state at least one of ``terms``."""
    wanted = [t for t in terms if t]
    return [s.label for s in sources if any(_present(t, s.text.lower()) for t in wanted)]
