"""The owner's pagination rules, enforced and verified on real PDF files.

Each scenario builds a CV whose layout breaks a rule, runs the real analysis / re-flow / condense
code, then reads the resulting *file* back: pages, sections, every moved line's glyphs. Nothing
about the layout is mocked; only the language model that proposes shorter wording is a stand-in.
"""

from __future__ import annotations

import dataclasses
import json
import re

import pytest

from app.core.resume_tailoring import condense
from app.core.resume_tailoring.pdf_fit import fit_pagination
from app.core.resume_tailoring.pdf_paginate import analyse
from app.core.resume_tailoring.pdf_reflow import fit_deficit, reflow_to_rules
from app.core.resume_tailoring.plan import EditPlan, ProposedEdit
from tests import pdf_tools
from tests import pdf_cv_factory as factory

LABELS = (("education", "Education & Qualifications"), ("experience", "Work & Leadership Experience"))
EXTRA = (
    "Captain of the university data club, running weekly sessions for 60 members.",
    "Volunteer mentor for a coding charity, teaching Python to 12 learners.",
)
ORDER = ("skills", "education", "experience", "extra", "certifications")


def make(tmp_path, name, *, style="serif_teal", pad=0, jobs=1, **style_kw):
    base = factory.CONTENTS["data_scientist"]
    key = f"_pag_{name}"
    factory.CONTENTS[key] = dataclasses.replace(
        base, extracurricular=EXTRA, labels=LABELS, order=ORDER, pad=pad, jobs=base.jobs * jobs
    )
    chosen = style
    if style_kw:
        chosen = f"_pag_style_{name}"
        factory.STYLES[chosen] = dataclasses.replace(factory.STYLES[style], **style_kw)
    try:
        return factory.make_cv(tmp_path / f"{name}.pdf", chosen, key)
    finally:
        factory.CONTENTS.pop(key, None)
        factory.STYLES.pop(f"_pag_style_{name}", None)


def rules(pagination):
    return {r.rule: r for r in pagination.rules}


class TestAnalysis:
    def test_a_compliant_cv_passes_every_rule(self, tmp_path):
        result = analyse(make(tmp_path, "ok", jobs=2))
        assert result.ok and all(r.ok for r in result.rules), [r.detail for r in result.violations]

    def test_extra_curricular_part_way_down_a_page_is_reported_with_where(self, tmp_path):
        found = rules(analyse(make(tmp_path, "mid")))["extra_curricular_new_page"]
        assert not found.ok and "part-way down page 1" in found.detail

    def test_a_heading_stranded_at_the_foot_of_a_page_is_reported(self, tmp_path):
        found = rules(analyse(make(tmp_path, "pad", pad=10)))["no_orphans"]
        assert not found.ok and "ends with the heading" in found.detail

    def test_education_and_work_split_across_pages_is_reported(self, tmp_path):
        found = rules(analyse(make(tmp_path, "split", jobs=2, pad=4)))["education_and_work_same_page"]
        assert not found.ok and "pages" in found.detail

    def test_the_report_names_every_rule(self, tmp_path):
        names = {r["rule"] for r in analyse(make(tmp_path, "names")).to_dict()["rules"]}
        assert names == {
            "education_and_work_same_page", "extra_curricular_new_page", "first_separator_on_page_one",
            "no_orphans", "no_blank_pages",
        }

    def test_a_rule_about_a_missing_section_is_not_applicable(self, tmp_path):
        plain = factory.make_cv(tmp_path / "plain.pdf", "serif_teal", "data_scientist")
        found = rules(analyse(plain))
        assert not found["extra_curricular_new_page"].applicable and found["extra_curricular_new_page"].ok


class TestReflow:
    @pytest.mark.parametrize("scenario", [{"name": "mid"}, {"name": "pad", "pad": 10}, {"name": "above", "rule_above": True}])
    def test_rules_are_met_by_moving_content_not_changing_it(self, tmp_path, scenario):
        src = make(tmp_path, **scenario)
        out = tmp_path / "out.pdf"
        result = reflow_to_rules(src, out)

        assert result.ok and result.applied, (result.reason, result.problems)
        after = analyse(out)
        assert after.ok, [r.detail for r in after.violations]
        assert after.pages == 2 and rules(after)["extra_curricular_new_page"].ok
        # The same words, in the same order, in the same fonts, sizes and colours.
        assert [r.text for r in after.rows if r.kind == "text"] == [r.text for r in analyse(src).rows if r.kind == "text"]
        assert pdf_tools.flat_text(out).replace(" ", "") == pdf_tools.flat_text(src).replace(" ", "")

    def test_lines_that_did_not_need_to_move_are_pixel_identical(self, tmp_path):
        src = make(tmp_path, "mid")
        out = tmp_path / "out.pdf"
        assert reflow_to_rules(src, out).applied
        before, after = pdf_tools.pixels(src, 0), pdf_tools.pixels(out, 0)
        # Everything above Extra-Curricular's old position is untouched on page 1.
        cut = int(500 * 96 / 72)
        assert abs(before[:cut] - after[:cut]).max() <= 48 and int((abs(before[:cut] - after[:cut]) > 48).sum()) == 0

    def test_a_compliant_file_is_left_alone(self, tmp_path):
        src = make(tmp_path, "ok", jobs=2)
        out = tmp_path / "out.pdf"
        result = reflow_to_rules(src, out)
        assert result.ok and not result.applied and not out.exists()

    def test_a_layout_that_needs_content_removed_is_refused_not_forced(self, tmp_path):
        src = make(tmp_path, "toolong", jobs=3)
        out = tmp_path / "out.pdf"
        result = reflow_to_rules(src, out)
        assert not result.ok and not result.applied and not out.exists()
        assert "without removing content" in result.reason
        deficit = fit_deficit(analyse(src))
        assert deficit and deficit[0] > 0


class _Shortener:
    """Stands in for the model: returns each bullet with trailing words removed."""

    def __init__(self, *, add_word: bool = False):
        self.add_word = add_word
        self.calls = 0

    async def complete_with_structured_output(self, *, prompt, **_kwargs):
        self.calls += 1
        rows = json.loads(prompt.split("BULLETS:\n", 1)[1].split("\n\nFor each bullet", 1)[0])
        edits = []
        for row in rows:
            words = row["text"].rstrip(".").split()
            need = row["remove_at_least_chars_to_save_a_line"]
            index = len(words) - 2
            while index > 4 and len(row["text"]) - len(" ".join(words)) < need:
                word = words[index].lower().strip(",;")
                if not re.search(r"\d", word) and word not in ("python", "sql"):
                    words.pop(index)
                index -= 1
            text = " ".join(words).rstrip(",;") + "."
            if self.add_word:
                text = text.replace(".", " dramatically.")
            edits.append(ProposedEdit(
                line_id=row["line_id"], action="tweak", after_text=text, reason="Removed trailing detail.",
                evidence=row["text"], keywords_added=[], level="1_clarity",
            ))
        return EditPlan(edits=edits)


class TestCondense:
    async def test_a_section_that_is_a_little_too_long_is_shortened_to_fit(self, tmp_path):
        src = make(tmp_path, "over", jobs=3)
        out = tmp_path / "fit.pdf"
        llm = _Shortener()
        result = await fit_pagination(src, out, llm=llm, protected_terms=["python", "sql"])

        assert result.status == "condensed", result.report
        after = analyse(out)
        assert after.ok, [r.detail for r in after.violations]
        assert result.condensed and all(len(new) < len(old) for old, new in result.condensed.values())
        # Words were only ever removed.
        for old, new in result.condensed.values():
            assert set(re.findall(r"[a-z]+", new.lower())) <= set(re.findall(r"[a-z]+", old.lower()))
        text = pdf_tools.flat_text(out)
        assert "Northwind Logistics" in text and "Brightside Retail" in text  # employers untouched
        assert pdf_tools.page_count(out) >= 2

    async def test_a_proposal_that_adds_a_word_is_rejected_and_the_file_is_left_alone(self, tmp_path):
        src = make(tmp_path, "over2", jobs=3)
        out = tmp_path / "fit.pdf"
        result = await fit_pagination(src, out, llm=_Shortener(add_word=True))
        assert result.status == "not_met" and not result.condensed
        assert out.read_bytes() == src.read_bytes()

    async def test_without_a_model_an_infeasible_layout_is_reported_not_forced(self, tmp_path):
        src = make(tmp_path, "over3", jobs=3)
        out = tmp_path / "fit.pdf"
        result = await fit_pagination(src, out, llm=None)
        assert result.status == "not_met" and result.report["deficit_points"] > 0
        assert out.read_bytes() == src.read_bytes()

    async def test_a_compliant_file_is_copied_unchanged(self, tmp_path):
        src = make(tmp_path, "fine", jobs=2)
        out = tmp_path / "fit.pdf"
        result = await fit_pagination(src, out, llm=_Shortener())
        assert result.status == "compliant" and out.read_bytes() == src.read_bytes()

    async def test_re_flow_alone_is_used_when_it_is_enough(self, tmp_path):
        src = make(tmp_path, "mid2")
        out = tmp_path / "fit.pdf"
        llm = _Shortener()
        result = await fit_pagination(src, out, llm=llm)
        assert result.status == "reflowed" and llm.calls == 0 and analyse(out).ok


class TestCondenseRules:
    PROTECTED = ["python", "sql"]

    def test_only_removing_words_is_acceptable(self):
        old = "Built a demand forecasting model in Python and SQL covering 1,200 SKUs, cutting error by 18%."
        assert condense.check(old, "Built a forecasting model in Python and SQL covering 1,200 SKUs, cutting error by 18%.", self.PROTECTED) is None

    @pytest.mark.parametrize(
        ("new", "why"),
        [
            ("Built a forecasting model in Python and SQL covering 1,200 SKUs, cutting error by 20%.", "figure"),
            ("Built a forecasting model in Python covering 1,200 SKUs, cutting error by 18%.", "protected term"),
            ("Built a forecasting model in Python and SQL, dramatically cutting error by 18%.", "adds words"),
            ("Built a demand forecasting model in Python and SQL covering 1,200 SKUs, cutting error by 18%.", "unchanged"),
            ("Built a model in Python and SQL.", "figure"),
            ("Built a model.", "figure"),
        ],
    )
    def test_everything_else_is_rejected(self, new, why):
        old = "Built a demand forecasting model in Python and SQL covering 1,200 SKUs, cutting error by 18%."
        problem = condense.check(old, new, self.PROTECTED)
        assert problem is not None and why.split()[0] in problem.lower()


class TestInThePipeline:
    JD = "Data Scientist\n\nRequirements\nPython and SQL\nA/B testing and experimentation\nstatistics\n"

    def _plan(self, src):
        from app.core.resume_tailoring.pdf_layout import build_document

        doc = build_document(str(src))
        line = next(ln for ln in doc.bullets() if "experimentation framework" in ln.text)
        return EditPlan(edits=[ProposedEdit(
            line_id=line.id, action="tweak", after_text=line.text.replace("with A/B testing", "with A/B testing and statistics"),
            reason="Uses the posting's wording.", evidence="The bullet already describes A/B testing.",
            keywords_added=["statistics"], level="4_keyword_alignment",
        )])

    async def test_a_tailored_pdf_comes_out_obeying_the_pagination_rules(self, tmp_path):
        from app.core.resume_tailoring.pdf_pipeline import tailor_pdf
        from tests.unit.test_pdf_tailoring_loop import SequenceLLM

        src = make(tmp_path, "pipe")
        assert not analyse(src).ok
        result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=self.JD, job_title="Data Scientist",
                                  llm=SequenceLLM([self._plan(src)]), target=1)

        assert result.status == "generated"
        pagination = result.details["pagination"]
        assert pagination["status"] == "reflowed" and pagination["after"]["ok"] is True
        assert analyse(tmp_path / "out.pdf").ok and pdf_tools.page_count(tmp_path / "out.pdf") == 2
        assert "and statistics for routing" in pdf_tools.flat_text(tmp_path / "out.pdf")
        assert result.details["ats_scored_from"] == "generated_pdf"

    async def test_a_file_with_no_wording_edits_still_obeys_the_pagination_rules(self, tmp_path):
        from app.core.resume_tailoring.pdf_pipeline import tailor_pdf
        from tests.unit.test_pdf_tailoring_loop import SequenceLLM

        src = make(tmp_path, "pipe2")
        assert not analyse(src).ok
        result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=self.JD, job_title="Data Scientist",
                                  llm=SequenceLLM([EditPlan()]))
        assert not result.audit.changes, "no wording was edited"
        assert result.status == "generated", "the layout fix is itself a result"
        assert result.details["pagination"]["status"] == "reflowed"
        assert analyse(tmp_path / "out.pdf").ok
        assert pdf_tools.flat_text(tmp_path / "out.pdf") == pdf_tools.flat_text(src)

    async def test_a_compliant_file_with_no_edits_is_returned_byte_for_byte(self, tmp_path):
        from app.core.resume_tailoring.pdf_pipeline import tailor_pdf
        from tests.unit.test_pdf_tailoring_loop import SequenceLLM

        src = make(tmp_path, "pipe3", jobs=2)
        assert analyse(src).ok
        result = await tailor_pdf(src, tmp_path / "out.pdf", job_text=self.JD, job_title="Data Scientist",
                                  llm=SequenceLLM([EditPlan()]))
        assert result.status == "unchanged" and result.details["pagination"]["status"] == "compliant"
        assert (tmp_path / "out.pdf").read_bytes() == src.read_bytes()
