"""Golden scenarios: a real CV PDF and a real posting through the whole PDF tailoring pipeline.

Only the language model is replaced, by a stand-in that returns a fixed edit plan, so each run is
deterministic. Everything else is the production code path: the PDF is parsed with its layout,
the validator accepts or rejects each edit on its merits, accepted edits are written into the
page, the file is checked, re-read, and scored.

For every scenario the assertions are the acceptance criteria, applied to the generated file:
it opens, has the same pages, keeps every employer/title/date/heading, differs from the original
only in the paragraphs that were edited, changes no pixel outside them, adds only supported
keywords, and carries an ATS score computed from the file itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.core.resume_tailoring.evidence import score
from app.core.resume_tailoring.jobspec import parse_job
from app.core.resume_tailoring.pdf_layout import build_document
from app.core.resume_tailoring.pdf_pipeline import MAX_ROUNDS, tailor_pdf
from app.core.resume_tailoring.plan import BANNED_PHRASES, EditPlan, ProposedEdit
from tests import pdf_tools
from tests.pdf_cv_factory import CONTENTS, make_cv

EVIDENCE = (
    "The summary and this bullet already describe working with stakeholders, "
    "workshops and customer feedback in this role."
)


class StubLLM:
    """Returns one fixed plan, whatever it is asked."""

    def __init__(self, build_plan):
        self.build_plan = build_plan
        self.calls = 0
        self.prompts: list[str] = []

    async def complete_with_structured_output(self, *, prompt, **_kwargs):
        self.calls += 1
        self.prompts.append(prompt)
        return self.build_plan


@dataclass
class Scenario:
    id: str
    role: str
    style: str
    content: str
    job_title: str
    job_text: str
    #: (fragment identifying the bullet, old wording, new wording, keywords added)
    edits: list[tuple[str, str, str, list[str]]] = field(default_factory=list)
    #: fragments of bullets whose edit must be applied
    applied: list[str] = field(default_factory=list)
    #: validator rule expected for each edit that must be rejected, by fragment
    rejected: dict[str, str] = field(default_factory=dict)
    #: terms the posting wants that the CV cannot evidence: they must not appear in the output
    unsupported: list[str] = field(default_factory=list)


SCENARIOS = [
    Scenario(
        "data_scientist", "Data Scientist", "serif_teal", "data_scientist", "Data Scientist",
        "Data Scientist. We need strong Python and SQL, time series forecasting, experimentation and "
        "A/B testing, Airflow pipelines and model monitoring. You will present findings to "
        "stakeholders and mentor analysts. Nice to have: dbt, Tableau.",
        edits=[
            ("Designed an experimentation framework", "rollout decisions across", "rollout decisions for stakeholders across", ["stakeholders"]),
            ("Productionised batch scoring", "with monitoring for data drift", "with model monitoring for data drift", ["model monitoring"]),
        ],
        applied=["Designed an experimentation framework", "Productionised batch scoring"],
    ),
    Scenario(
        "business_analyst", "Business Analyst", "sans_plain", "business_analyst", "Business Analyst",
        "Business Analyst. Requirements gathering, stakeholder workshops, process mapping, user stories "
        "and acceptance criteria, SQL and Power BI reporting, user acceptance testing, Agile delivery.",
        edits=[("Documented current and future state", "technology teams.", "technology teams and stakeholder workshops.", ["workshops"])],
        applied=["Documented current and future state"],
    ),
    Scenario(
        "ai_product_manager", "AI Product Manager", "serif_navy_small", "product_manager", "AI Product Manager",
        "AI Product Manager. Own the roadmap for LLM-powered features, prompt engineering, evaluation "
        "of generative models, customer discovery, stakeholder management and analytics.",
        edits=[
            ("Defined success metrics", "funnel analysis in SQL", "funnel analytics in SQL", ["analytics"]),
            ("Ran customer discovery", "turned the findings into", "turned the Looker findings into", ["Looker"]),
        ],
        applied=["Defined success metrics"],
        rejected={"Ran customer discovery": "unsupported_technology"},
        unsupported=["LLM", "prompt engineering"],
    ),
    Scenario(
        "product_manager", "Product Manager", "sans_green", "product_manager", "Product Manager",
        "Product Manager. Roadmapping, customer discovery, stakeholder management, analytics and SQL, "
        "working with engineering and design in an Agile team.",
        edits=[("Managed the integrations portfolio", "onboarding process.", "onboarding process with design.", ["design"])],
        applied=["Managed the integrations portfolio"],
    ),
    Scenario(
        "data_analyst", "Data Analyst", "sans_green", "data_scientist", "Data Analyst",
        "Data Analyst. SQL, dashboards in Tableau or Power BI, reporting to stakeholders, "
        "data quality and analysis of commercial performance.",
        edits=[
            ("Created Tableau dashboards", "to track weekly sales", "to track weekly sales in Looker", ["Looker"]),
            ("Designed an experimentation framework", "rollout decisions across", "rollout decisions for stakeholders across", ["stakeholders"]),
        ],
        applied=["Designed an experimentation framework"],
        rejected={"Created Tableau dashboards": "unsupported_technology"},
        unsupported=["Power BI"],
    ),
    Scenario(
        "technical_product", "Technical Product Manager", "serif_teal", "product_manager", "Technical Product Manager",
        "Technical Product Manager. API design, microservices, SQL, integrations with partners, "
        "technical requirements and working closely with engineering teams.",
        edits=[("Defined success metrics", "at the verification step.", "at the verification step with engineering.", ["engineering"])],
        applied=["Defined success metrics"],
        unsupported=["microservices", "API design"],
    ),
    Scenario(
        "unsupported_skills", "Data Scientist (platform)", "sans_plain", "data_scientist", "Data Scientist",
        "Data Scientist. Kubernetes, Spark, Databricks, MLflow, and Terraform are essential. "
        "Python and SQL required.",
        edits=[("Productionised batch scoring", "on Airflow and Docker", "on Airflow, Docker and payments", ["payments"])],
        rejected={"Productionised batch scoring": "excluded_domain"},
        unsupported=["Kubernetes", "Spark", "Databricks", "MLflow", "Terraform"],
    ),
    Scenario(
        "synonym_heavy", "Business Analyst (synonyms)", "serif_navy_small", "business_analyst", "Business Analyst",
        "Business Analyst. Elicitation of requirements from stakeholders, stakeholder engagement, "
        "documentation of as-is and to-be processes, defect triage and sign-off during UAT.",
        edits=[("Documented current and future state", "technology teams.", "technology teams and stakeholders.", ["stakeholders"])],
        applied=["Documented current and future state"],
    ),
    Scenario(
        "many_requirements", "Product Manager (long list)", "serif_teal", "product_manager", "Senior Product Manager",
        "Senior Product Manager. Mandatory: roadmapping, discovery, SQL, experimentation, pricing strategy, "
        "go-to-market, payments regulation, B2B SaaS, stakeholder management, Agile, OKRs, "
        "A/B testing, analytics, mentoring product managers.",
        edits=[("Defined success metrics", "funnel analysis in SQL", "funnel analytics in SQL", ["analytics"])],
        applied=["Defined success metrics"],
        unsupported=["pricing strategy", "go-to-market"],
    ),
    Scenario(
        "minimal_posting", "Data Scientist (minimal)", "serif_teal", "data_scientist", "Data Scientist",
        "Data Scientist. Python.",
        edits=[],
    ),
    Scenario(
        "edit_that_does_not_fit", "Data Scientist (overflow)", "sans_green", "data_scientist", "Data Scientist",
        "Data Scientist. Python, SQL, forecasting, experimentation, stakeholders.",
        edits=[
            ("Mentored 3 junior analysts", "code reviews and weekly", "code reviews for experimentation stakeholders and weekly", ["stakeholders"]),
            ("Designed an experimentation framework", "rollout decisions across", "rollout decisions for stakeholders across", ["stakeholders"]),
        ],
        applied=["Designed an experimentation framework"],
        rejected={"Mentored 3 junior analysts": "layout"},
    ),
    Scenario(
        "attempt_to_change_a_fact", "Product Manager (facts)", "sans_plain", "product_manager", "Product Manager",
        "Product Manager. Roadmaps and discovery.",
        edits=[("Owned the invoicing product roadmap", "a team of 8 engineers", "a team of 12 engineers", [])],
        rejected={"Owned the invoicing product roadmap": "fabricated_metric"},
    ),
]


def _plan_for(original, scenario: Scenario) -> EditPlan:
    edits = []
    for fragment, old, new, keywords in scenario.edits:
        line = next(ln for ln in original.bullets() if fragment in ln.text)
        assert old in line.text, f"scenario wording drifted: {old!r} not in {line.text!r}"
        edits.append(
            ProposedEdit(
                line_id=line.id, action="tweak", after_text=line.text.replace(old, new),
                reason="Works the posting's own wording into a bullet that already shows it.",
                evidence=EVIDENCE, keywords_added=keywords, level="4_keyword_alignment",
            )
        )
    return EditPlan(edits=edits)


def _text(path) -> str:
    return pdf_tools.flat_text(path)


def _pixels_outside_edits(src, out, regions) -> int:
    changed = 0
    for i in range(pdf_tools.page_count(src)):
        mask = abs(pdf_tools.pixels(src, i) - pdf_tools.pixels(out, i)) > 48
        for rect in regions.get(i, []):
            mask[max(0, int((rect[1] - 4) * 96 / 72)): int((rect[3] + 4) * 96 / 72) + 1,
                 max(0, int((rect[0] - 4) * 96 / 72)): int((rect[2] + 4) * 96 / 72) + 1] = False
        changed += int(mask.sum())
    return changed


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
async def test_golden_scenario(scenario: Scenario, tmp_path):
    src = make_cv(tmp_path / "base.pdf", scenario.style, scenario.content)
    original = build_document(str(src))
    llm = StubLLM(_plan_for(original, scenario))
    out = tmp_path / "tailored.pdf"

    result = await tailor_pdf(src, out, job_text=scenario.job_text, job_title=scenario.job_title, llm=llm)

    # --- the file exists, opens, and is the same document ---------------------------------------
    # A validator rejection earns one corrective retry; a layout-only skip happens afterwards.
    retried = any(rule != "layout" for rule in scenario.rejected.values())
    first_round = 2 if retried else 1
    # Rounds after the first run only while the score is under target and a weakly evidenced
    # requirement remains; each costs at most one call (two with a corrective retry).
    assert out.exists() and first_round <= llm.calls <= first_round + 2 * (MAX_ROUNDS - 1)
    assert result.details["rounds"][0]["round"] == 1
    assert pdf_tools.page_count(out) == pdf_tools.page_count(src)
    assert pdf_tools.page_boxes(out) == pdf_tools.page_boxes(src)
    assert all(n > 20 for n in pdf_tools.word_counts(out)), "no page may be blank"
    assert result.check.ok, result.check.problems
    assert result.details["formatting_preserved"] is True

    # --- only the intended paragraphs changed -------------------------------------------------
    applied_lines = [next(ln for ln in original.bullets() if frag in ln.text) for frag in scenario.applied]
    assert len(result.edit.applied) == len(scenario.applied)
    assert {c.line_id for c in result.audit.changes} == {ln.id for ln in applied_lines}

    for fragment, rule in scenario.rejected.items():
        line = next(ln for ln in original.bullets() if fragment in ln.text)
        rejection = [r for r in result.audit.rejected_edits if r.line_id == line.id]
        assert rejection and rejection[0].rule == rule, (fragment, result.audit.rejected_edits)

    final = result.final
    original_text = original.to_text()
    for line in original.all_lines():
        if not line.editable:
            assert line.text in final.to_text(), f"fixed line changed: {line.text!r}"
    assert final.fingerprint() == original.fingerprint()
    assert final.headings() == original.headings()

    # --- facts survive --------------------------------------------------------------------------
    cv = CONTENTS[scenario.content]
    final_text = _text(out).replace(" ", " ")
    for employer, title, dates, _ in cv.jobs:
        assert employer in final_text and title in final_text and dates in final_text
    for entry in cv.education:
        assert entry in final_text

    # --- keywords: supported ones arrive, unsupported ones never do --------------------------------
    for change in result.audit.changes:
        for keyword in change.keywords_added:
            assert keyword.lower() in change.after_text.lower()
    for term in scenario.unsupported:
        assert term.lower() not in final_text.lower()
        assert term.lower() not in original_text.lower()
    changed_text = " ".join(c.after_text.lower() for c in result.audit.changes)
    assert not any(phrase in changed_text for phrase in BANNED_PHRASES)
    assert result.audit.claims_added == 0 and result.details["introduced_numbers"] == {}

    # --- ATS comes from the generated file ------------------------------------------------------
    spec = parse_job(scenario.job_text, title=scenario.job_title)
    independent = score(final, spec, pdf=out)  # a fresh evaluation of the file on disk
    from app.core.ats_engine import evaluate

    assert evaluate(build_document(str(out)), scenario.job_text, scenario.job_title, pdf=out).ats_match == independent.total
    assert result.after.total == independent.total
    assert result.after.total >= result.before.total
    assert result.details["ats_scored_from"] == "generated_pdf"

    # --- nothing outside the edited paragraphs moved ------------------------------------------------
    regions: dict[int, list] = {}
    for outcome in result.edit.applied:
        regions.setdefault(outcome.page, []).append(outcome.rect)
    assert _pixels_outside_edits(src, out, regions) <= 12

    # --- status is honest -----------------------------------------------------------------------
    assert result.status == ("generated" if scenario.applied else "unchanged")
    if not scenario.applied:
        assert out.read_bytes() == src.read_bytes() or _text(out) == _text(src)


async def test_the_planner_is_told_how_much_room_each_line_has(tmp_path):
    src = make_cv(tmp_path / "base.pdf", "serif_teal", "data_scientist")
    llm = StubLLM(EditPlan())
    await tailor_pdf(src, tmp_path / "out.pdf", job_text="Data Scientist. Python.", job_title="Data Scientist", llm=llm)
    assert '"max_chars"' in llm.prompts[0]
