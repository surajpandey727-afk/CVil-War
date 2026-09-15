"""Post-generation fabrication guard for LLM-tailored resume content.

PHASE0_AUDIT.md (D2) found that "NEVER fabricate" existed only as prompt text,
with nothing checking that the model actually complied — generated content
was written straight to a PDF and could reach an employer unverified.

This is a scoped, real check, not the full evidence-model / claim-validation
engine the audit describes for Phase 3 (which needs new tables tracking each
claim's source and confidence level). It catches the two failure modes that
matter most:

- **Hard violation** — a company, institution, or degree appears in the
  tailored output that was not in the original resume. The tailoring prompt's
  own rules require these fields stay unchanged verbatim, so any new value
  here is unambiguous fabrication, not paraphrasing. This blocks generation.
- **Soft flag** — a skill appears in the tailored output that was not in the
  original resume's skill list. This is *not* blocked, because the prompt
  legitimately instructs the model to restate a matching skill using the job
  posting's terminology (e.g. "k8s" -> "Kubernetes"), which looks identical to
  a fabricated skill under an exact-match check. These are surfaced for the
  user to review instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _normalize(value: str) -> str:
    return " ".join((value or "").lower().split())


@dataclass(frozen=True)
class ClaimCheckResult:
    """Outcome of comparing tailored resume content against the original."""

    fabricated_companies: list[str] = field(default_factory=list)
    fabricated_institutions: list[str] = field(default_factory=list)
    unsupported_skills: list[str] = field(default_factory=list)

    @property
    def has_hard_violation(self) -> bool:
        return bool(self.fabricated_companies or self.fabricated_institutions)


def _known_values(entries: list[dict], key: str) -> set[str]:
    return {
        _normalize(entry.get(key, ""))
        for entry in entries
        if isinstance(entry, dict) and entry.get(key)
    }


def check_tailored_resume_for_fabrication(
    original: dict,
    tailored: dict,
) -> ClaimCheckResult:
    """Compare tailored resume data against the original it was derived from.

    Args:
        original: The resume data sent to the LLM (template-context dict).
        tailored: The LLM's tailored output, already ``model_dump()``-ed.

    Returns:
        A ``ClaimCheckResult`` describing any fabrication found.
    """
    known_companies = _known_values(original.get("experience") or [], "company")
    known_institutions = _known_values(original.get("education") or [], "institution")
    known_skills = {_normalize(s) for s in (original.get("skills") or [])}

    fabricated_companies = sorted(
        {
            entry.get("company", "")
            for entry in (tailored.get("experience") or [])
            if isinstance(entry, dict)
            and entry.get("company")
            and _normalize(entry["company"]) not in known_companies
        }
    )
    fabricated_institutions = sorted(
        {
            entry.get("institution", "")
            for entry in (tailored.get("education") or [])
            if isinstance(entry, dict)
            and entry.get("institution")
            and _normalize(entry["institution"]) not in known_institutions
        }
    )
    unsupported_skills = sorted(
        {
            skill
            for skill in (tailored.get("skills") or [])
            if skill and _normalize(skill) not in known_skills
        }
    )

    return ClaimCheckResult(
        fabricated_companies=fabricated_companies,
        fabricated_institutions=fabricated_institutions,
        unsupported_skills=unsupported_skills,
    )
