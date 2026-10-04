"""Read a job description into tiered, typed requirements (brief sections 3, 4, 8, 9).

Deterministic: no model call, so the same posting always yields the same requirements and a score
can be reproduced. Built on the existing skill lexicon (``resume_tailoring.jobspec``) and extended
with the vocabulary of the roles this product is used for.

Real postings rarely carry clean "Requirements" and "Nice to have" headings, so tiers are decided
from three signals together: the heading the line sits under (when there is one), how often the
posting repeats the term, and whether the title names it. A flat posting is ranked by emphasis
instead of being treated as if everything in it were optional.
"""
# ruff: noqa: E501
# Skill lexicons and a boilerplate regex are single long literals.

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.core.ats_engine.taxonomy import ReqTier, ReqType, classify
from app.core.resume_tailoring.jobspec import Tier, _tier_for_line, lexicon

#: Skills beyond the base lexicon: tools and craft terms that postings for product, data, analyst
#: and AI roles name constantly. Matched exactly like the base lexicon.
EXTRA_LEXICON: tuple[str, ...] = tuple(
    """product analytics|stakeholder|roadmapping|backlog|user experience|ux|customer journey|personas|wireframes
    |prototyping|figma|jira|confluence|tableau|power bi|looker|excel|statistics|hypothesis
    testing|regression
    |forecasting|time series|clustering|classification|pytorch|tensorflow|scikit-
    learn|pandas|numpy|nosql|mongodb
    |redis|react|typescript|javascript|java|golang|fastapi|flask|django|monitoring|observability|security|privacy
    |gdpr|responsible ai|ai governance|ethics|explainability|risk
    management|audit|finance|banking|insurance
    |healthcare|fintech|saas|b2b|b2c|e-commerce|marketplace|pricing|monetisation|monetization|growth|retention
    |activation|onboarding|conversion|funnel|churn|revenue|p&l|budget|vendor management|procurement
    |change management|enablement|executive communication|requirements
    gathering|automation|rpa|workflow
    |integration|data analysis|data visualisation|data visualization|reporting|root cause
    analysis|use cases
    |feasibility|benefits realisation|fine-tuning|mlflow|langchain|openai|hugging face|ai
    agents|copilot
    |conversational ai|chatbots|speech|recommendation
    systems|personalisation|personalization|customer success
    |customer experience|service design|design thinking|technical product|api integration|data
    science
    |predictive modelling|predictive modeling|deep learning|reinforcement learning|neural
    networks|statistics
    |data strategy|ai strategy|roi|cost reduction|operational efficiency|digital transformation""".replace(
        "\n", ""
    ).split("|")
)

_BOILERPLATE = re.compile(
    r"equal opportunit|reasonable adjustment|benefits|salary|compensation|perks|we offer|401\(?k\)?|pension|"
    r"holiday|diversity|disability|apply now|privacy notice|cookie|about us|who we are",
    re.I,
)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:\+\s*)?years?", re.I)
_CERT = re.compile(
    r"\b(PMP|CSPO|CSM|PSPO|CFA|CPA|CISSP|AWS Certified[\w\s-]{0,30}|Azure [A-Z]{1,3}-\d{3}|"
    r"certification in [\w\s]{3,30}|professionally certified)\b"
)
_REQUIRED_WORDS = re.compile(r"\b(required|must|essential|mandatory|minimum|need)\b", re.I)

_VERB_FAMILIES: dict[str, frozenset[str]] = {
    "build": frozenset(
        [
            "build",
            "built",
            "building",
            "develop",
            "developed",
            "developing",
            "create",
            "created",
            "creating",
            "implement",
            "implemented",
        ]
    ),
    "design": frozenset(["design", "designed", "designing", "architect", "architected"]),
    "lead": frozenset(["lead", "led", "leading", "leadership"]),
    "manage": frozenset(["manage", "managed", "managing", "management"]),
    "own": frozenset(["own", "owned", "owning", "ownership", "accountable"]),
    "deliver": frozenset(
        [
            "deliver",
            "delivered",
            "delivering",
            "ship",
            "shipped",
            "shipping",
            "launch",
            "launched",
            "launching",
            "release",
            "released",
        ]
    ),
    "define": frozenset(
        ["define", "defined", "defining", "specify", "specified", "scope", "scoped"]
    ),
    "drive": frozenset(
        ["drive", "drove", "driving", "champion", "championed", "influence", "influenced"]
    ),
    "collaborate": frozenset(
        [
            "collaborate",
            "collaborated",
            "collaborating",
            "partner",
            "partnered",
            "partnering",
            "align",
            "aligned",
            "coordinate",
            "coordinated",
            "liaise",
            "liaised",
            "engage",
            "engaged",
            "cross-functional",
            "stakeholder",
            "stakeholders",
        ]
    ),
    "analyse": frozenset(
        [
            "analyse",
            "analyze",
            "analysed",
            "analyzed",
            "analysing",
            "analyzing",
            "analysis",
            "evaluate",
            "evaluated",
        ]
    ),
    "optimise": frozenset(
        [
            "optimise",
            "optimize",
            "optimised",
            "optimized",
            "improve",
            "improved",
            "improving",
            "reduce",
            "reduced",
            "increase",
            "increased",
        ]
    ),
    "communicate": frozenset(
        [
            "communicate",
            "communicated",
            "present",
            "presented",
            "presenting",
            "articulate",
            "report",
            "reported",
        ]
    ),
    "deploy": frozenset(
        [
            "deploy",
            "deployed",
            "deploying",
            "productionise",
            "productionize",
            "productionised",
            "productionized",
            "automate",
            "automated",
        ]
    ),
    "research": frozenset(
        ["research", "researched", "discover", "discovered", "interview", "interviewed"]
    ),
    "mentor": frozenset(["mentor", "mentored", "coach", "coached", "train", "trained"]),
    "prioritise": frozenset(
        ["prioritise", "prioritize", "prioritised", "prioritized", "roadmap", "triage"]
    ),
    "measure": frozenset(
        [
            "measure",
            "measured",
            "track",
            "tracked",
            "monitor",
            "monitored",
            "instrument",
            "instrumented",
        ]
    ),
}

_SENIORITY = (
    (1, re.compile(r"\b(intern|graduate|junior|jr|associate|entry)\b", re.I)),
    (5, re.compile(r"\b(director|vp|vice president|chief|head of)\b", re.I)),
    (4, re.compile(r"\b(principal|staff|lead|squad lead|group)\b", re.I)),
    (3, re.compile(r"\b(senior|sr|iii)\b", re.I)),
)


@dataclass(frozen=True)
class EvalRequirement:
    """One thing the posting asks for, with how much it matters and what kind of thing it is."""

    term: str
    tier: ReqTier
    type: ReqType
    mentions: int = 1
    in_title: bool = False
    source: str = ""
    #: Wordings that count as the same thing, for verb-family requirements.
    family: frozenset[str] = frozenset()


@dataclass
class RequirementSet:
    items: list[EvalRequirement] = field(default_factory=list)
    title: str = ""
    years_required: int | None = None
    degree_level: int = 0  # 0 none, 1 bachelor, 2 master, 3 doctorate
    degree_required: bool = False
    certifications: list[str] = field(default_factory=list)
    certification_required: bool = False
    seniority: int = 2
    duties: list[str] = field(default_factory=list)
    usable: bool = True  # False when the posting has no text to read

    def by_tier(self, tier: ReqTier) -> list[EvalRequirement]:
        return [r for r in self.items if r.tier is tier]


def _scan_terms() -> tuple[str, ...]:
    return tuple(sorted({*lexicon(), *EXTRA_LEXICON}, key=len, reverse=True))


def _find(low: str, term: str) -> int:
    return len(re.findall(rf"(?<![\w/]){re.escape(term)}(?![\w/])", low))


def _title_seniority(title: str, years: int | None) -> int:
    level = 2
    for value, pattern in _SENIORITY:
        if pattern.search(title or ""):
            level = value
            break
    if years is not None:
        level = max(level, 4 if years >= 8 else 3 if years >= 5 else level)
    return level


def _degree(lines: list[str]) -> tuple[int, bool]:
    level, required = 0, False
    for line in lines:
        low = line.lower()
        found = (
            3
            if re.search(r"\b(phd|doctorate|doctoral)\b", low)
            else 2
            if re.search(r"\b(master'?s?|msc|mba|ma\b)", low)
            else 1
            if re.search(r"\b(bachelor'?s?|bsc|undergraduate|degree)\b", low)
            else 0
        )
        if found:
            level = max(level, found)
            if _REQUIRED_WORDS.search(low) or "or equivalent" in low:
                required = True
    return level, required


def _rank_tiers(entries: list[dict]) -> None:
    """Assign final tiers: heading signal first, emphasis (title, repetition) second."""
    mandatory = [e for e in entries if e["block"] is Tier.MANDATORY]
    key = lambda e: (-int(e["in_title"]), -e["mentions"], e["first"])  # noqa: E731
    flat = not mandatory and not any(e["block"] is Tier.PREFERRED for e in entries)

    if flat:
        ranked = sorted(
            entries, key=lambda e: (-(e["mentions"] + 3 * int(e["in_title"])), e["first"])
        )
        n = len(ranked)
        cuts = (min(8, max(3, math.ceil(0.30 * n))), math.ceil(0.60 * n), math.ceil(0.85 * n))
        for index, entry in enumerate(ranked):
            entry["tier"] = (
                ReqTier.CRITICAL
                if index < cuts[0]
                else ReqTier.IMPORTANT
                if index < cuts[1]
                else ReqTier.SUPPORTING
                if index < cuts[2]
                else ReqTier.NICE
            )
        return

    critical_n = min(10, max(3, math.ceil(0.5 * len(mandatory))))
    for index, entry in enumerate(sorted(mandatory, key=key)):
        entry["tier"] = ReqTier.CRITICAL if index < critical_n else ReqTier.IMPORTANT
    for entry in entries:
        if entry["block"] is Tier.PREFERRED:
            entry["tier"] = (
                ReqTier.IMPORTANT
                if entry["in_title"] or entry["mentions"] >= 2
                else ReqTier.SUPPORTING
            )
        elif entry["block"] is Tier.CONTEXTUAL:
            entry["tier"] = (
                ReqTier.IMPORTANT
                if entry["in_title"]
                else ReqTier.SUPPORTING
                if entry["mentions"] >= 2
                else ReqTier.NICE
            )


def extract_requirements(job_text: str, title: str = "") -> RequirementSet:
    """The posting as tiered, typed requirements."""
    text = job_text or ""
    result = RequirementSet(title=(title or "").strip(), usable=bool(text.strip()))
    if not result.usable:
        return result

    terms = _scan_terms()
    block = Tier.CONTEXTUAL
    entries: dict[str, dict] = {}
    duties: list[str] = []
    mandatory_lines: list[str] = []
    all_lines: list[str] = []
    title_low = result.title.lower()
    order = 0

    for raw in text.splitlines():
        line = raw.strip()
        if not line or (_BOILERPLATE.search(line) and len(line) < 220):
            continue
        block = _tier_for_line(line, block)
        all_lines.append(line)
        if block is Tier.MANDATORY:
            mandatory_lines.append(line)
        if block is Tier.CONTEXTUAL and len(line) > 40:
            duties.append(line)
        low = f" {line.lower()} "
        covered: list[str] = []
        for term in terms:
            if any(term in longer and term != longer for longer in covered):
                continue
            hits = _find(low, term)
            if not hits:
                continue
            covered.append(term)
            entry = entries.setdefault(
                term,
                {"term": term, "mentions": 0, "block": block, "first": order, "source": line[:200]},
            )
            entry["mentions"] += hits
            order += 1
            if (block is Tier.MANDATORY) or (
                block is Tier.PREFERRED and entry["block"] is Tier.CONTEXTUAL
            ):
                entry["block"] = block
                entry["source"] = line[:200]

    for entry in entries.values():
        entry["in_title"] = _find(f" {title_low} ", entry["term"]) > 0
    ordered = list(entries.values())
    _rank_tiers(ordered)

    years_line = next((ln for ln in mandatory_lines if _YEARS.search(ln)), None) or next(
        (ln for ln in all_lines if _YEARS.search(ln) and re.search(r"experience", ln, re.I)), None
    )
    if years_line:
        found = [int(v) for v in _YEARS.findall(years_line)]
        result.years_required = min(found) if found else None

    result.degree_level, result.degree_required = _degree(all_lines)
    certs = sorted({m.group(0).strip() for ln in all_lines for m in _CERT.finditer(ln)})
    result.certifications = certs[:6]
    result.certification_required = any(
        _REQUIRED_WORDS.search(ln) and _CERT.search(ln) for ln in all_lines
    )
    result.duties = duties[:30]
    result.seniority = _title_seniority(result.title, result.years_required)

    items = [
        EvalRequirement(
            e["term"], e["tier"], classify(e["term"]), e["mentions"], e["in_title"], e["source"]
        )
        for e in ordered
    ]
    items += _derived(result, duties)
    result.items = items
    return result


def _derived(spec: RequirementSet, duties: list[str]) -> list[EvalRequirement]:
    """Requirements that are not skill terms: years, degree, certification, core duties."""
    out: list[EvalRequirement] = []
    if spec.years_required:
        out.append(
            EvalRequirement(
                f"{spec.years_required}+ years of experience", ReqTier.CRITICAL, ReqType.EXPERIENCE
            )
        )
    if spec.degree_level:
        label = ("bachelor's", "master's", "doctorate")[spec.degree_level - 1] + " degree"
        out.append(
            EvalRequirement(
                label,
                ReqTier.CRITICAL if spec.degree_required else ReqTier.SUPPORTING,
                ReqType.EDUCATION,
            )
        )
    for cert in spec.certifications[:3]:
        tier = ReqTier.CRITICAL if spec.certification_required else ReqTier.SUPPORTING
        out.append(EvalRequirement(cert, tier, ReqType.CERTIFICATION))

    counts: dict[str, int] = {}
    low_duties = " ".join(duties).lower()
    for family, words in _VERB_FAMILIES.items():
        counts[family] = sum(len(re.findall(rf"\b{re.escape(w)}\b", low_duties)) for w in words)
    floor = 2 if len(duties) > 8 else 1  # a short posting says each duty once
    ranked = [f for f, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if n >= floor][
        :6
    ]
    for index, family in enumerate(ranked):
        tier = (
            ReqTier.CRITICAL
            if index < 2
            else ReqTier.IMPORTANT
            if index < 4
            else ReqTier.SUPPORTING
        )
        out.append(
            EvalRequirement(
                f"{family} (core responsibility)",
                tier,
                ReqType.RESPONSIBILITY,
                counts[family],
                False,
                "",
                _VERB_FAMILIES[family],
            )
        )
    return out


def verb_family(name: str) -> frozenset[str]:
    return _VERB_FAMILIES.get(name, frozenset())


_CACHE: dict[tuple[str, str], RequirementSet] = {}
_CACHE_LIMIT = 64


def requirements_for(job_text: str, title: str = "") -> RequirementSet:
    """:func:`extract_requirements`, remembered per posting.

    Reading a posting is most of what evaluating a résumé costs, and it does not depend on the
    résumé. Tailoring scores the same posting dozens of times, so each caller gets its own copy of
    one extraction rather than repeating it.
    """
    import copy

    key = (job_text, title)
    found = _CACHE.get(key)
    if found is None:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.pop(next(iter(_CACHE)))
        found = _CACHE[key] = extract_requirements(job_text, title)
    return copy.deepcopy(found)
