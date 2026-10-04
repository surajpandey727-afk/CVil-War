"""The ATS target loop: more rounds only while they earn points, and never at the truth's expense.

Rounds after the first work on lines not yet edited and on requirements the CV evidences weakly.
A round that does not raise the score is discarded, a result that scores below the original is
never shipped, and a target that cannot be reached honestly is reported as such.
"""

from __future__ import annotations

from unittest.mock import patch

from app.core.resume_tailoring.evidence import AtsScore
from app.core.resume_tailoring.pdf_layout import build_document
from app.core.resume_tailoring.pdf_pipeline import tailor_pdf
from app.core.resume_tailoring.plan import EditPlan, ProposedEdit
from tests import pdf_tools
from tests.pdf_cv_factory import make_cv

JD = """Data Scientist

Requirements
Python and SQL
scikit-learn
PyTorch
statistics
"""
EVIDENCE = "The bullet already describes this work for the same team."


class SequenceLLM:
    """Returns the next prepared plan on each call (the last one repeats)."""

    def __init__(self, plans: list[EditPlan]):
        self.plans = plans
        self.calls = 0
        self.prompts: list[str] = []

    async def complete_with_structured_output(self, *, prompt, **_kwargs):
        self.prompts.append(prompt)
        plan = self.plans[min(self.calls, len(self.plans) - 1)]
        self.calls += 1
        return plan


def _edit(doc, fragment: str, old: str, new: str, keywords: list[str]) -> ProposedEdit:
    line = next(ln for ln in doc.bullets() if fragment in ln.text)
    assert old in line.text, line.text
    return ProposedEdit(
        line_id=line.id, action="tweak", after_text=line.text.replace(old, new),
        reason="Uses the posting's wording for work the bullet already describes.",
        evidence=EVIDENCE, keywords_added=keywords, level="4_keyword_alignment",
    )


def _setup(tmp_path):
    src = make_cv(tmp_path / "base.pdf", "serif_teal", "data_scientist")
    return src, build_document(str(src))


async def test_a_second_round_that_raises_the_score_is_kept(tmp_path):
    src, doc = _setup(tmp_path)
    first = EditPlan(edits=[_edit(doc, "experimentation framework", "with A/B testing", "with A/B testing and statistics", ["statistics"])])
    second = EditPlan(edits=[_edit(doc, "demand forecasting model", "Python and LightGBM", "Python, LightGBM and PyTorch", ["pytorch"])])
    llm = SequenceLLM([first, second])
    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Scientist", llm=llm, target=95)

    rounds = result.details["rounds"]
    assert rounds[0]["outcome"] == "kept" and rounds[1]["outcome"] == "kept"
    assert rounds[1]["focus"], "the second round is told which requirements are only weakly evidenced"
    assert len(result.audit.changes) == 2 and result.after.total > result.before.total
    first_line = next(c.line_id for c in result.audit.changes if "statistics" in c.after_text)
    assert f'"line_id": "{first_line}"' not in llm.prompts[1].split("THE ONLY LINES YOU MAY EDIT")[1]
    assert "FOCUS FOR THIS ROUND" in llm.prompts[1]
    text = pdf_tools.flat_text(tmp_path / "out.pdf")
    assert "and statistics for routing" in text and "LightGBM and PyTorch" in text


async def test_a_round_that_does_not_raise_the_score_is_discarded(tmp_path):
    src, doc = _setup(tmp_path)
    first = EditPlan(edits=[_edit(doc, "experimentation framework", "with A/B testing", "with A/B testing and statistics", ["statistics"])])
    cosmetic = EditPlan(edits=[_edit(doc, "Mentored 3 junior analysts", "Mentored 3 junior analysts", "Coached 3 junior analysts", [])])
    llm = SequenceLLM([first, cosmetic])
    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Scientist", llm=llm, target=95)
    outcomes = [r["outcome"] for r in result.details["rounds"]]
    assert outcomes[0] == "kept" and any("discarded" in o or "no further" in o for o in outcomes[1:])
    assert "Coached" not in pdf_tools.flat_text(tmp_path / "out.pdf")


async def test_it_stops_as_soon_as_the_target_is_reached(tmp_path):
    src, doc = _setup(tmp_path)
    plan = EditPlan(edits=[_edit(doc, "experimentation framework", "with A/B testing", "with A/B testing and statistics", ["statistics"])])
    llm = SequenceLLM([plan])
    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Scientist", llm=llm, target=1)
    assert len(result.details["rounds"]) == 1 and llm.calls == 1
    assert result.details["ats_target_reached"] is True and result.details["ats_target_note"] == ""


async def test_an_unreachable_target_is_reported_not_faked(tmp_path):
    src, doc = _setup(tmp_path)
    jd = JD + "Tableau\nLooker\nTerraform\nKubernetes\n"
    llm = SequenceLLM([EditPlan()])
    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=jd, job_title="Data Scientist", llm=llm, target=99)
    assert result.details["ats_target_reached"] is False
    assert result.details["ats_target_note"]
    assert result.after.total == result.before.total  # nothing was invented to chase the number


async def test_a_result_that_scores_below_the_original_is_never_shipped(tmp_path):
    src, doc = _setup(tmp_path)
    plan = EditPlan(edits=[_edit(doc, "experimentation framework", "with A/B testing", "with A/B testing and statistics", ["statistics"])])
    llm = SequenceLLM([plan])

    from app.core.resume_tailoring import pdf_pipeline

    real = pdf_pipeline.score
    seen: list[int] = []

    def worse_after(document, spec, coverage=None, *, pdf=None):
        got = real(document, spec, coverage, pdf=pdf)
        seen.append(1)
        if len(seen) > 1:  # everything after the first (original) scoring looks worse
            return AtsScore(
                total=max(0, got.total - 20), components=got.components, weights=got.weights, matched=got.matched,
                semantic=got.semantic, missing_mandatory=got.missing_mandatory,
                missing_preferred=got.missing_preferred, constrained_by=got.constrained_by, evaluation=got.evaluation,
            )
        return got

    with patch.object(pdf_pipeline, "score", worse_after):
        result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Scientist", llm=llm, target=95)

    assert result.status == "unchanged" and not result.audit.changes
    assert (tmp_path / "out.pdf").read_bytes() == src.read_bytes()
    assert "lowered" in result.details["ats_target_note"]


async def test_the_evaluation_of_the_final_file_is_attached(tmp_path):
    src, doc = _setup(tmp_path)
    plan = EditPlan(edits=[_edit(doc, "experimentation framework", "with A/B testing", "with A/B testing and statistics", ["statistics"])])
    result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=JD, job_title="Data Scientist", llm=SequenceLLM([plan]), target=95)
    before, after = result.details["evaluation_before"], result.details["evaluation_after"]
    assert after["ats_match"] == result.after.total and before["ats_match"] == result.before.total
    for key in ("parsing", "shortlist", "tiers", "problems", "verdict", "recruiter"):
        assert key in after
