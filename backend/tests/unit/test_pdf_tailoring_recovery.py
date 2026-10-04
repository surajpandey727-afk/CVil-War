"""Recovering facts a CV left out, from trusted evidence — and refusing everything else.

The CV is a selection of the candidate's career. A fact its PDF omitted may be surfaced when a
trusted source states it, the change log says which source, and the same validator still
rejects anything no source supports.
"""

from __future__ import annotations

from app.core.resume_tailoring.pdf_layout import build_document
from app.core.resume_tailoring.pdf_pipeline import tailor_pdf
from app.core.resume_tailoring.plan import EditPlan, ProposedEdit
from app.core.resume_tailoring.trusted import TrustedSource, profile_source, resume_source
from tests import pdf_tools
from tests.pdf_cv_factory import make_cv
from tests.unit.test_pdf_tailoring_golden import EVIDENCE, StubLLM

PROFILE = TrustedSource(
    "Career profile (Settings)",
    "Created Tableau dashboards used by 40 store managers across 12 regions to track weekly sales and stock.\n"
    "Wrote SQL transformations in dbt to consolidate five reporting sources into one model.",
)
JD = "Data Analyst. Tableau dashboards, SQL, reporting to regional stakeholders."


def _plan(doc, fragment, old, new, keywords=()):
    line = next(ln for ln in doc.bullets() if fragment in ln.text)
    return EditPlan(edits=[ProposedEdit(
        line_id=line.id, action="tweak", after_text=line.text.replace(old, new),
        reason="Surfaces a detail the candidate's own records state for this work.",
        evidence="[Career profile (Settings)] " + EVIDENCE, keywords_added=list(keywords), level="4_keyword_alignment",
    )]), line


async def test_a_fact_the_cv_omitted_is_surfaced_and_attributed_to_its_source(tmp_path):
    src = make_cv(tmp_path / "cv.pdf", "serif_navy_small", "data_scientist")
    doc = build_document(str(src))
    plan, line = _plan(doc, "Created Tableau dashboards", "40 store managers", "40 store managers across 12 regions")

    result = await tailor_pdf(
        src, tmp_path / "out.pdf", job_text=JD, job_title="Data Analyst", llm=StubLLM(plan), trusted=[PROFILE]
    )

    assert result.status == "generated" and result.check.ok
    change = result.audit.changes[0]
    assert "across 12 regions" in change.after_text
    assert "12" in change.recovered_terms and "regions" in change.recovered_terms
    assert change.evidence_sources == ["Career profile (Settings)"]
    assert result.details["recovered_from_trusted_evidence"][line.id]["sources"] == ["Career profile (Settings)"]
    assert result.details["trusted_sources_consulted"] == [
        "Career profile (Settings)",
        "Owner-declared experience (standing brief)",
    ]


async def test_the_same_edit_is_rejected_when_no_source_states_it(tmp_path):
    src = make_cv(tmp_path / "cv.pdf", "serif_navy_small", "data_scientist")
    doc = build_document(str(src))
    plan, line = _plan(doc, "Created Tableau dashboards", "40 store managers", "40 store managers across 12 regions")

    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Analyst", llm=StubLLM(plan))

    assert result.status == "unchanged"
    assert [r.rule for r in result.audit.rejected_edits] == ["fabricated_metric"]


async def test_a_real_figure_cannot_be_moved_onto_an_unrelated_bullet(tmp_path):
    # "12" is in the profile, but only against the dashboards. Attaching it to the mentoring
    # bullet would turn a true number into a false claim.
    src = make_cv(tmp_path / "cv.pdf", "serif_navy_small", "data_scientist")
    doc = build_document(str(src))
    plan, _ = _plan(doc, "Mentored 3 junior analysts", "junior analysts", "junior analysts across 12 regions")

    result = await tailor_pdf(
        src, tmp_path / "out.pdf", job_text=JD, job_title="Data Analyst", llm=StubLLM(plan), trusted=[PROFILE]
    )

    assert result.status == "unchanged"
    assert [r.rule for r in result.audit.rejected_edits] == ["fabricated_metric"]


async def test_a_technology_no_source_states_is_still_rejected_with_evidence_available(tmp_path):
    src = make_cv(tmp_path / "cv.pdf", "serif_navy_small", "data_scientist")
    doc = build_document(str(src))
    plan, _ = _plan(doc, "Created Tableau dashboards", "to track weekly sales", "to track weekly sales in Looker", ["Looker"])

    result = await tailor_pdf(
        src, tmp_path / "out.pdf", job_text=JD, job_title="Data Analyst", llm=StubLLM(plan), trusted=[PROFILE]
    )

    assert result.status == "unchanged"
    assert result.audit.rejected_edits[0].rule == "unsupported_technology"
    assert "looker" not in pdf_tools.flat_text(tmp_path / "out.pdf").lower()


async def test_evidence_is_shown_to_the_planner_and_recoverable_terms_are_not_forbidden(tmp_path):
    src = make_cv(tmp_path / "cv.pdf", "serif_teal", "data_scientist")
    llm = StubLLM(EditPlan())
    await tailor_pdf(
        src, tmp_path / "out.pdf", job_text="Data Scientist. Kubernetes, Tableau, Python.", job_title="Data Scientist",
        llm=llm, trusted=[TrustedSource("Previous résumé: Asha_older.pdf", "Deployed the forecasting service on Kubernetes for the commercial team.")],
    )
    prompt = llm.prompts[0]
    assert "TRUSTED CAREER EVIDENCE" in prompt and "Previous résumé: Asha_older.pdf" in prompt
    recoverable = prompt.split("recoverable, where a bullet fits:")[1].split("THE FULL CV")[0]
    assert "kubernetes" in recoverable.lower()
    forbidden = prompt.split("TERMS YOU MUST NOT WRITE")[1].split("KEYWORDS YOU MAY WRITE")[0]
    assert "kubernetes" not in forbidden.lower()


def test_profile_and_resume_sources_are_built_from_the_candidates_own_records():
    assert profile_source(None) is None and profile_source({}) is None
    source = profile_source({"experience": [{"company": "Acme", "description": "Built a forecasting model"}], "skills": ["SQL"]})
    assert source and "Built a forecasting model" in source.text and "SQL" in source.text
    assert resume_source("old.pdf", "  ") is None
    assert resume_source("old.pdf", "Led a team").label == "Previous résumé: old.pdf"
