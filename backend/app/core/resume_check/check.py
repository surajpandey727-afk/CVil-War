"""The deterministic résumé check: every number here is reproducible from the inputs.

Overall fit = 0.45 x must-have coverage + 0.20 x nice-to-have coverage
            + 0.20 x ATS keyword coverage + 0.15 x section health.

Coverage is weighted by each skill's weight for the target, so missing a heavily-weighted core
skill costs more than missing a peripheral one. Bands reuse the Skill Radar's thresholds so the
two screens never disagree about what "decent" means.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.resume_check.sections import (
    Review,
    review_experience,
    review_formatting,
    review_skills,
    review_summary,
)
from app.core.resume_check.suggest import rule_suggestions
from app.core.resume_check.targets import Target, TargetSkill
from app.core.resume_check.text import find_evidence, split_blocks
from app.core.skills.aggregate import DECENT_FLOOR, STRONG_CEILING, _present
from app.schemas.resume_check import (
    AtsKeywords,
    CheckTarget,
    CorpusInfo,
    Evidence,
    FitScore,
    MatchedSkill,
    MissingSkill,
    ResumeCheckResponse,
    ScoreComponent,
    SectionReview,
)

WEIGHTS = {"must_have": 0.45, "nice_to_have": 0.20, "ats": 0.20, "sections": 0.15}
# The multiplication sign, built from its code point so the source stays ASCII-unambiguous.
_X = chr(0xD7)
FORMULA = (
    f"0.45 {_X} must-have coverage + 0.20 {_X} nice-to-have coverage "
    f"+ 0.20 {_X} ATS keyword coverage + 0.15 {_X} section health"
)


@dataclass(frozen=True)
class CheckInput:
    resume_id: str
    resume_name: str
    resume_text: str
    target: Target
    target_info: CheckTarget
    uk_demand: dict[str, int]
    uk_jobs_scanned: int


def _coverage(skills: list[TargetSkill], present: set[str]) -> tuple[float, int, int]:
    total = sum(t.weight for t in skills)
    got = sum(t.weight for t in skills if t.skill.key in present)
    hit = sum(1 for t in skills if t.skill.key in present)
    return (got / total if total else 1.0), hit, len(skills)


def _band(score: float) -> str:
    if score >= STRONG_CEILING:
        return "strong"
    return "decent" if score >= DECENT_FLOOR else "gap"


def build_check(inp: CheckInput) -> tuple[ResumeCheckResponse, dict[str, Review]]:
    """Run the full deterministic check. Also returns the raw reviews for the LLM layer."""
    blocks = split_blocks(inp.resume_text)
    low = inp.resume_text.lower()
    target = inp.target.skills
    present = {t.skill.key for t in target if _present(t.skill, low)}

    musts = [t for t in target if t.must_have]
    nices = [t for t in target if not t.must_have]
    must_cov, must_hit, must_n = _coverage(musts, present)
    nice_cov, nice_hit, nice_n = _coverage(nices, present)
    ats_skills = [t for t in target if t.skill.ats]
    ats_found = [t.skill.label for t in ats_skills if t.skill.key in present]
    ats_missing = [t.skill.label for t in ats_skills if t.skill.key not in present]
    ats_cov = len(ats_found) / len(ats_skills) if ats_skills else 1.0

    reviews = {
        "summary": review_summary(blocks, target, inp.target_info.title),
        "experience": review_experience(blocks),
        "skills": review_skills(blocks, target),
        "formatting": review_formatting(inp.resume_text, blocks),
    }
    section_health = sum(r.score for r in reviews.values()) / len(reviews)

    components = [
        ScoreComponent(
            key="must_have",
            label="Must-have skills",
            weight=WEIGHTS["must_have"],
            score=round(must_cov, 4),
            detail=f"{must_hit} of {must_n} must-have skills shown (weighted by importance)."
            if must_n
            else "The target names no must-have skills; counted as covered.",
        ),
        ScoreComponent(
            key="nice_to_have",
            label="Nice-to-have skills",
            weight=WEIGHTS["nice_to_have"],
            score=round(nice_cov, 4),
            detail=f"{nice_hit} of {nice_n} nice-to-have skills shown."
            if nice_n
            else "No nice-to-have skills named; counted as covered.",
        ),
        ScoreComponent(
            key="ats",
            label="ATS keyword coverage",
            weight=WEIGHTS["ats"],
            score=round(ats_cov, 4),
            detail=f"{len(ats_found)} of {len(ats_skills)} screenable keywords found verbatim.",
        ),
        ScoreComponent(
            key="sections",
            label="Section health",
            weight=WEIGHTS["sections"],
            score=round(section_health, 4),
            detail="Average of the summary, experience, skills and formatting reviews.",
        ),
    ]
    overall = round(sum(c.weight * c.score for c in components), 4)

    missing = [t for t in target if t.skill.key not in present]
    missing.sort(key=lambda t: (not t.must_have, -inp.uk_demand.get(t.skill.key, 0), -t.weight))
    skills_text = " ".join(b.text for b in blocks if b.section == "skills")
    suggestions = rule_suggestions(
        resume_text=inp.resume_text,
        target=target,
        missing_ranked=missing,
        demand=inp.uk_demand,
        scanned=inp.uk_jobs_scanned,
        reviews=reviews,
        skills_text=skills_text,
    )

    response = ResumeCheckResponse(
        resume_id=inp.resume_id,
        resume_name=inp.resume_name,
        target=inp.target_info,
        score=FitScore(
            overall=overall, band=_band(overall), components=components, formula=FORMULA
        ),
        matched_skills=[
            MatchedSkill(
                key=t.skill.key,
                label=t.skill.label,
                category=t.skill.category,
                must_have=t.must_have,
                evidence=[Evidence(quote=q, section=s) for q, s in find_evidence(t.skill, blocks)],
            )
            for t in target
            if t.skill.key in present
        ],
        missing_skills=[
            MissingSkill(
                key=t.skill.key,
                label=t.skill.label,
                category=t.skill.category,
                must_have=t.must_have,
                uk_demand=inp.uk_demand.get(t.skill.key, 0),
                uk_demand_share=round(inp.uk_demand.get(t.skill.key, 0) / inp.uk_jobs_scanned, 4)
                if inp.uk_jobs_scanned
                else 0.0,
            )
            for t in missing
        ],
        ats_keywords=AtsKeywords(
            coverage=round(ats_cov, 4),
            total=len(ats_skills),
            found=ats_found,
            missing=ats_missing,
        ),
        sections=[
            SectionReview(
                key=r.key, label=r.label, status=r.status, score=r.score, findings=r.findings
            )
            for r in reviews.values()
        ],
        suggestions=suggestions,
        corpus=CorpusInfo(uk_jobs_scanned=inp.uk_jobs_scanned),
    )
    return response, reviews
