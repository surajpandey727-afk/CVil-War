"""Declared experience: the owner's brief names capabilities the CV leaves out, and the validators
let those be written, while finance, invented figures and invented employers stay out.
"""

from __future__ import annotations

from app.core.llm.prompts.standing import RESUME_GENERATION_STANDARD
from app.core.resume_tailoring.declared import (
    LABEL,
    declared_source,
    declared_text,
    excluded_terms_added,
    with_declared,
)
from app.core.resume_tailoring.model import LineKind
from app.core.resume_tailoring.plan import ProposedEdit
from app.core.resume_tailoring.validate import _skill_row_problem, check_edit

CV = (
    "Built a batch scoring service in Python and Docker for the logistics team.\n"
    "Created dashboards used by 40 store managers to track weekly sales."
)
BEFORE = "Created dashboards used by 40 store managers to track weekly sales."
EVIDENCE = "[Owner-declared experience (standing brief)] Power BI, Tableau, Dashboarding, BI."


def _edit(after: str, evidence: str = EVIDENCE) -> ProposedEdit:
    return ProposedEdit(
        line_id="L1", action="tweak", after_text=after, reason="Names the BI tooling.",
        evidence=evidence, keywords_added=["Power BI"], level="4_keyword_alignment",
    )


def test_the_brief_is_stored_with_the_new_instructions_verbatim():
    assert "DO NOT CONFUSE “NOT CURRENTLY ON MY CV” WITH “I HAVE NOT DONE IT”" in RESUME_GENERATION_STANDARD
    assert "The end point is not a better CV." in RESUME_GENERATION_STANDARD
    assert "Absence from the current resume must NEVER be interpreted as absence of experience." in RESUME_GENERATION_STANDARD
    assert "excluding finance related modules in tech" in RESUME_GENERATION_STANDARD


def test_the_declaration_is_a_trusted_source_added_once():
    source = declared_source()
    assert source.label == LABEL and "Power BI" in source.text and "Tableau" in source.text
    assert len(with_declared(with_declared(()))) == 1
    assert "finance" not in declared_text().lower()


def test_a_declared_tool_can_be_written_where_the_cv_never_named_it():
    after = "Created Power BI dashboards used by 40 store managers to track weekly sales."
    assert check_edit(_edit(after), BEFORE, CV, evidence_text=declared_text()) is None


def test_the_same_edit_is_refused_when_nothing_declares_the_tool():
    after = "Created Power BI dashboards used by 40 store managers to track weekly sales."
    refused = check_edit(_edit(after), BEFORE, CV, evidence_text="")
    assert refused is not None and refused.rule in ("unsupported_technology", "unsupported_claim")


def test_a_tool_nobody_declared_is_still_refused():
    after = "Created Looker dashboards used by 40 store managers to track weekly sales."
    refused = check_edit(_edit(after), BEFORE, CV, evidence_text=declared_text())
    assert refused is not None and refused.rule == "unsupported_technology"


def test_declared_experience_never_supplies_a_figure():
    after = "Created Power BI dashboards used by 400 store managers to track weekly sales."
    refused = check_edit(_edit(after), BEFORE, CV, evidence_text=declared_text())
    assert refused is not None and refused.rule == "fabricated_metric"


def test_finance_technology_is_never_written():
    after = "Created dashboards used by 40 store managers to track weekly payments and ledger data."
    refused = check_edit(_edit(after), BEFORE, CV, evidence_text=declared_text())
    assert refused is not None and refused.rule == "excluded_domain"
    assert excluded_terms_added("sold to banks", "built core banking and KYC checks") == [
        "core banking",
        "kyc",
    ]
    assert excluded_terms_added("Payments team", "Payments team lead") == []


def test_a_longer_clause_is_allowed_when_a_trusted_source_backs_it():
    after = (
        "Created Power BI and Tableau dashboards for decision support, used by 40 store managers "
        "to track weekly sales and stakeholder reporting."
    )
    assert check_edit(_edit(after), BEFORE, CV, evidence_text=declared_text()) is None


class TestSkillRows:
    ROW = "Infrastructure: Docker, Kubernetes, Terraform"

    def test_items_may_be_appended(self):
        assert _skill_row_problem(self.ROW, self.ROW + ", AWS") is None
        assert _skill_row_problem(self.ROW, self.ROW + ", AWS, Power BI") is None

    def test_the_label_and_existing_items_must_stay(self):
        assert _skill_row_problem(self.ROW, "Cloud: Docker, Kubernetes, Terraform, AWS")
        assert _skill_row_problem(self.ROW, "Infrastructure: Docker, Terraform, Kubernetes, AWS")
        assert _skill_row_problem(self.ROW, "Infrastructure: Docker, Terraform")

    def test_a_row_must_actually_grow_and_not_by_much(self):
        assert _skill_row_problem(self.ROW, self.ROW)
        assert _skill_row_problem(self.ROW, self.ROW + " and AWS")
        assert _skill_row_problem(self.ROW, self.ROW + ", A, B, C, D, E, F, G")

    def test_a_skill_row_edit_goes_through_the_row_rules(self):
        edit = _edit(self.ROW + ", AWS")
        assert check_edit(edit, self.ROW, self.ROW, evidence_text=declared_text(), kind=LineKind.SKILL) is None
        bad = _edit("Cloud: Docker, AWS")
        refused = check_edit(bad, self.ROW, self.ROW, evidence_text=declared_text(), kind=LineKind.SKILL)
        assert refused is not None


class TestSkillRowsInAPdf:
    ROWS = "Languages: Python, SQL, scikit-learn\nInfrastructure: Docker, Airflow\nVisualisation: Tableau"

    def _cv(self, tmp_path):
        import dataclasses

        from tests import pdf_cv_factory as factory

        key = "_skill_rows"
        factory.CONTENTS[key] = dataclasses.replace(factory.CONTENTS["data_scientist"], skills=self.ROWS)
        try:
            return factory.make_cv(tmp_path / "rows.pdf", "serif_teal", key)
        finally:
            factory.CONTENTS.pop(key, None)

    def test_skill_rows_are_found_and_made_editable(self, tmp_path):
        from app.core.resume_tailoring.pdf_layout import build_document

        doc = build_document(str(self._cv(tmp_path)))
        rows = [ln for ln in doc.all_lines() if ln.kind is LineKind.SKILL]
        assert [r.text.split(":")[0] for r in rows] == ["Languages", "Infrastructure", "Visualisation"]
        assert all(doc.capacity[r.id] > len(r.text) for r in rows)

    async def test_a_declared_tool_is_appended_to_a_row_and_nothing_else_moves(self, tmp_path):
        from app.core.resume_tailoring.pdf_layout import build_document
        from app.core.resume_tailoring.pdf_pipeline import tailor_pdf
        from tests import pdf_tools

        src = self._cv(tmp_path)
        doc = build_document(str(src))
        row = next(r for r in doc.all_lines() if r.text.startswith("Visualisation"))

        class Stub:
            async def complete_with_structured_output(self, *, prompt, **_kw):
                from app.core.resume_tailoring.plan import EditPlan

                return EditPlan(edits=[_edit(row.text + ", Power BI").model_copy(update={"line_id": row.id})])

        result = await tailor_pdf(
            src, tmp_path / "out.pdf", job_text="Data Analyst. Power BI and Tableau dashboards, SQL.",
            job_title="Data Analyst", llm=Stub(), max_rounds=1,
        )
        assert result.status == "generated" and result.check.ok, result.check.problems
        text = pdf_tools.flat_text(tmp_path / "out.pdf")
        assert "Visualisation: Tableau, Power BI" in text
        assert [c.line_id for c in result.audit.changes] == [row.id]
        assert result.final.fingerprint() == result.original.fingerprint()
