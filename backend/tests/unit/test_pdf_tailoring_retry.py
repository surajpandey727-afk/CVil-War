"""One corrective retry: tell the model what was rejected and why, then take what is valid."""

from __future__ import annotations

from app.core.resume_tailoring.pdf_layout import build_document
from app.core.resume_tailoring.pdf_pipeline import tailor_pdf
from app.core.resume_tailoring.plan import EditPlan, ProposedEdit
from tests.pdf_cv_factory import make_cv
from tests.unit.test_pdf_tailoring_golden import EVIDENCE

JD = "Data Analyst. Tableau dashboards, SQL, reporting to stakeholders."


class SequenceLLM:
    def __init__(self, *plans):
        self.plans, self.prompts = list(plans), []

    async def complete_with_structured_output(self, *, prompt, **_):
        self.prompts.append(prompt)
        return self.plans[min(len(self.prompts) - 1, len(self.plans) - 1)]


def _edit(doc, fragment, old, new):
    line = next(ln for ln in doc.bullets() if fragment in ln.text)
    return ProposedEdit(
        line_id=line.id, action="tweak", after_text=line.text.replace(old, new), reason="Aligns wording.",
        evidence=EVIDENCE, keywords_added=[], level="4_keyword_alignment",
    )


async def test_a_rejected_edit_is_retried_with_the_reason_and_the_corrected_edit_is_used(tmp_path):
    src = make_cv(tmp_path / "cv.pdf", "serif_navy_small", "data_scientist")
    doc = build_document(str(src))
    bad = EditPlan(edits=[_edit(doc, "Analysed promotion", "performance", "performance with Looker")])
    good = EditPlan(edits=[_edit(doc, "Analysed promotion", "commercial director.", "commercial director and stakeholders.")])
    llm = SequenceLLM(bad, good)

    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Analyst", llm=llm)

    assert len(llm.prompts) == 2
    assert "REVIEW OF YOUR PREVIOUS ATTEMPT" in llm.prompts[1] and "unsupported_technology" in llm.prompts[1]
    assert result.status == "generated" and result.audit.rejected_edits == []
    assert "commercial director and stakeholders." in result.audit.changes[0].after_text


async def test_a_retry_that_is_still_invalid_changes_nothing_and_reports_the_rejection(tmp_path):
    src = make_cv(tmp_path / "cv.pdf", "serif_navy_small", "data_scientist")
    doc = build_document(str(src))
    bad = EditPlan(edits=[_edit(doc, "Analysed promotion", "performance", "performance with Looker")])
    llm = SequenceLLM(bad, bad)

    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Analyst", llm=llm)

    assert len(llm.prompts) == 2 and result.status == "unchanged"
    assert [r.rule for r in result.audit.rejected_edits] == ["unsupported_technology"], "reported once, not twice"


async def test_echoed_lines_do_not_trigger_a_retry(tmp_path):
    src = make_cv(tmp_path / "cv.pdf", "serif_navy_small", "data_scientist")
    doc = build_document(str(src))
    line = next(ln for ln in doc.bullets() if "Analysed promotion" in ln.text)
    echo = EditPlan(edits=[ProposedEdit(
        line_id=line.id, action="tweak", after_text=line.text, reason="none", evidence=EVIDENCE,
    )])
    llm = SequenceLLM(echo)

    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Analyst", llm=llm)

    assert len(llm.prompts) == 1 and result.status == "unchanged"
