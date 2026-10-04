"""The ATS + shortlisting evaluation engine: the ten properties the owner's brief requires.

Each test builds real résumé text and a real-shaped posting and asserts a behaviour, not a
number: critical requirements outweigh nice-to-haves, keyword stuffing earns nothing, semantic
matches are recognised, unsupported skills are not matches, demonstrated work beats a skills
list, seniority gaps and parsing failures are detected.
"""

from __future__ import annotations

import pytest

from app.core.ats_engine import evaluate, simulate
from app.core.ats_engine.matching import assess
from app.core.ats_engine.requirements import extract_requirements
from app.core.ats_engine.structure import analyse
from app.core.ats_engine.taxonomy import ReqTier, Strength
from app.core.resume_tailoring.extract import parse_resume_text

JD = """Senior Data Scientist

About the role
You will build predictive models, deploy ML pipelines and communicate findings to stakeholders.
You will lead experimentation and own forecasting for the commercial team across the business.

Requirements
5+ years of experience in data science
Strong Python and SQL
Machine learning in production
A/B testing and experimentation
Stakeholder management

Nice to have
Tableau
Airflow
"""

HEADER = "Asha Raman\nLondon, UK\nasha@example.com | +44 7700 900123 | linkedin.com/in/asha\n"


def _cv(skills: str, bullets: list[str], summary: str = "Data scientist.", title: str = "Senior Data Scientist") -> str:
    body = "\n".join(f"• {b}" for b in bullets)
    return (
        f"{HEADER}\nSUMMARY\n{summary}\n\nSKILLS\n{skills}\n\nEXPERIENCE\nNorthwind Ltd, London\n"
        f"{title}\nJanuary 2019 - Present\n{body}\n\nEDUCATION\nMSc Statistics, University of Leeds, 2018\n"
    )


STRONG = _cv(
    "Python, SQL, machine learning, A/B testing, stakeholder management, Airflow",
    [
        "Built a demand forecasting model in Python and SQL covering 1,200 SKUs, cutting forecast error by 18%.",
        "Deployed machine learning pipelines to production on Airflow, serving 40 stores with daily predictions.",
        "Led A/B testing and experimentation for routing changes, informing rollout decisions across 6 depots.",
        "Presented findings to commercial stakeholders and managed stakeholder expectations on three launches.",
        "Owned forecasting for the commercial team and mentored 3 analysts through weekly reviews.",
    ],
)
SKILLS_ONLY = _cv(
    "Python, SQL, machine learning, A/B testing, stakeholder management, Airflow, Tableau",
    ["Worked on reporting.", "Helped the team with data tasks.", "Attended meetings."],
)
STUFFED = _cv(
    "Python, SQL, machine learning, A/B testing, stakeholder management, Airflow, Tableau",
    [
        "Python SQL machine learning A/B testing stakeholder management experimentation forecasting Airflow Tableau Python SQL.",
        "Worked on reporting.",
    ],
)
VARIANT = _cv(
    "ML, Python, SQL",
    [
        "Trained and deployed ML models to production, improving retention forecasts by 12%.",
        "Worked across product, engineering and operations teams to ship the models.",
    ],
)
NO_SQL = _cv(
    "Python, machine learning, A/B testing, stakeholder management",
    [
        "Built a demand forecasting model in Python covering 1,200 SKUs, cutting forecast error by 18%.",
        "Deployed machine learning pipelines to production, serving 40 stores with daily predictions.",
        "Led A/B testing and experimentation for routing changes across 6 depots.",
        "Presented findings to commercial stakeholders and managed stakeholder expectations.",
    ],
)
JUNIOR = (
    f"{HEADER}\nSKILLS\nPython, SQL, machine learning\n\nEXPERIENCE\nStartup Ltd\nJunior Analyst\nJune 2024 - Present\n"
    "• Built a Python and SQL report that cut weekly effort by 20%.\n• Trained a machine learning model on sales data.\n\n"
    "EDUCATION\nBSc Mathematics, University of Pune, 2023\n"
)


def ev(text: str, jd: str = JD, title: str = "Senior Data Scientist"):
    return evaluate(parse_resume_text(text), jd, title)


def strength_of(evaluation, term: str) -> Strength:
    return next(a.strength for a in evaluation.assessments if a.requirement.term.lower() == term.lower())


class TestRequirementHierarchy:
    def test_requirements_are_tiered_and_typed(self):
        spec = extract_requirements(JD, "Senior Data Scientist")
        tiers = {r.term: r.tier for r in spec.items}
        assert tiers["python"] is ReqTier.CRITICAL and tiers["sql"] is ReqTier.CRITICAL
        assert tiers["tableau"] in (ReqTier.SUPPORTING, ReqTier.NICE)
        assert spec.years_required == 5 and spec.seniority == 3
        assert {r.type.value for r in spec.items} >= {"TECHNOLOGY", "EXPERIENCE", "RESPONSIBILITY"}

    def test_a_flat_posting_is_ranked_by_emphasis_not_treated_as_optional(self):
        spec = extract_requirements("Product Manager. Own the roadmap, roadmap, roadmap. Use SQL. Some Tableau.", "Product Manager")
        assert next(r for r in spec.items if r.term == "roadmap").tier is ReqTier.CRITICAL

    def test_boilerplate_is_not_a_requirement(self):
        spec = extract_requirements("Equal opportunity employer. We offer a pension and python lessons.\nRequirements\nSQL", "")
        assert [r.term for r in spec.items if r.term == "python"] == []


class TestEvidenceNotKeywordCount:
    def test_demonstrated_experience_outscores_a_skills_list(self):
        strong, listed = ev(STRONG), ev(SKILLS_ONLY)
        assert strength_of(strong, "python") >= Strength.DEMONSTRATED
        assert strength_of(listed, "python") is Strength.MENTIONED
        assert strong.ats_match > listed.ats_match + 10
        assert strong.shortlist > listed.shortlist

    def test_keyword_stuffing_does_not_inflate_the_score(self):
        stuffed, listed, strong = ev(STUFFED), ev(SKILLS_ONLY), ev(STRONG)
        assert strength_of(stuffed, "python") is Strength.MENTIONED  # a list of terms is not work
        assert stuffed.ats_match <= listed.ats_match + 3
        assert stuffed.ats_match < strong.ats_match - 10

    def test_repeating_a_keyword_in_one_line_earns_nothing_extra(self):
        once = ev(_cv("Python", ["Built a Python forecasting model, cutting error by 18%."]))
        many = ev(_cv("Python", ["Built a Python Python Python Python forecasting model, cutting error by 18%."]))
        assert strength_of(once, "python") == strength_of(many, "python")

    def test_semantic_and_variant_matches_are_recognised(self):
        variant = ev(VARIANT)
        found = next(a for a in variant.assessments if a.requirement.term == "machine learning")
        assert found.strength >= Strength.SUPPORTED and found.match == "variant"

    def test_unsupported_skills_are_not_treated_as_matches(self):
        strong = ev(STRONG.replace(", Airflow", ""))
        assert strength_of(strong, "tableau") is Strength.NONE
        assert any(f.requirement == "tableau" for f in strong.missing)


class TestWeighting:
    def test_missing_a_critical_requirement_costs_far_more_than_a_nice_to_have(self):
        base = ev(STRONG)
        lacks_critical = ev(NO_SQL)
        lacks_nice = ev(STRONG.replace(", Airflow", "").replace(" on Airflow", ""))
        assert base.ats_match - lacks_critical.ats_match >= 8
        assert (base.ats_match - lacks_nice.ats_match) < (base.ats_match - lacks_critical.ats_match)
        assert "sql" in [t.lower() for t in lacks_critical.constrained_by]

    def test_a_missing_critical_requirement_caps_the_score_openly(self):
        capped = ev(NO_SQL)
        assert capped.ats_match <= 84 and capped.constrained_by

    def test_components_are_published_and_sum_to_the_headline(self):
        e = ev(STRONG)
        assert set(e.components) == set(e.weights)
        assert abs(sum(e.weights.values()) - 1.0) < 1e-9
        assert e.ats_match == round(sum(e.components[k] * e.weights[k] for k in e.components)) or e.constrained_by


class TestSeniorityAndParsing:
    def test_a_seniority_mismatch_is_detected_and_explained(self):
        junior = ev(JUNIOR)
        assert junior.components["seniority"] < 100
        assert any("senior" in n.lower() for n in junior.seniority["notes"])  # type: ignore[union-attr]
        assert junior.shortlist < ev(STRONG).shortlist

    def test_parsing_is_a_separate_score(self):
        no_sections = ev("Asha\nI like data.\nPython SQL machine learning")
        assert no_sections.parsing < ev(STRONG).parsing
        assert no_sections.parsing_findings

    def test_a_pdf_with_no_text_fails_parsing(self, tmp_path):
        from reportlab.pdfgen import canvas

        blank = tmp_path / "blank.pdf"
        canvas.Canvas(str(blank)).save()
        report = evaluate(parse_resume_text(STRONG), JD, "Senior Data Scientist", pdf=str(blank))
        assert report.parsing < 80 and any("extractable" in f or "scan" in f for f in report.parsing_findings)

    def test_a_table_heavy_pdf_is_penalised(self, tmp_path):
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Table
        from reportlab.lib.styles import getSampleStyleSheet

        from tests.pdf_cv_factory import make_cv

        clean = make_cv(tmp_path / "clean.pdf", "serif_teal", "data_scientist")
        rows = [[f"Cell {r}-{c} text content here" for c in range(4)] for r in range(30)]
        path = tmp_path / "table.pdf"
        SimpleDocTemplate(str(path), pagesize=letter).build(
            [Paragraph("Asha Raman asha@example.com +44 7700 900123", getSampleStyleSheet()["Normal"]), Table(rows)]
        )
        doc = parse_resume_text(STRONG)
        assert evaluate(doc, JD, "x", pdf=str(clean)).parsing > evaluate(doc, JD, "x", pdf=str(path)).parsing


class TestHonestReporting:
    def test_ats_and_shortlist_are_separate_dimensions(self):
        stuffed = ev(STUFFED)
        assert stuffed.ats_match != stuffed.shortlist
        assert stuffed.shortlist_dimensions["impact"] < ev(STRONG).shortlist_dimensions["impact"]

    def test_the_required_outputs_are_present_and_specific(self):
        e = ev(SKILLS_ONLY)
        assert set(e.tiers) == {"critical", "important", "supporting", "nice_to_have"}
        assert e.tiers["critical"].total >= 4 and e.tiers["critical"].mentioned >= 1
        assert e.weak and all(f.note for f in e.weak)
        assert e.problems and all(p.what and p.where and p.why and p.effect for p in e.problems)
        assert 3 <= len(e.problems) <= 7 or len(e.problems) >= 1
        assert e.recruiter.signal in {"Strong", "Mixed", "Weak"} and len(e.recruiter.reasons) == 5
        assert e.verdict.ats_alignment in {"Strong", "Moderate", "Weak"}

    def test_the_tailoring_limit_names_what_would_be_fabrication(self):
        e = ev(NO_SQL)
        assert "sql" in e.verdict.tailoring_limit.lower() and "fabrication" in e.verdict.tailoring_limit.lower()

    def test_bands_describe_alignment_not_outcomes(self):
        assert ev(STRONG).band in {"Very strong alignment", "Strong alignment", "Moderate alignment", "Weak alignment", "Limited alignment"}

    def test_no_posting_text_scores_zero_rather_than_guessing(self):
        empty = ev(STRONG, jd="")
        assert empty.ats_match == 0 and empty.posting_usable is False

    def test_the_result_is_reproducible(self):
        assert ev(STRONG).to_dict() == ev(STRONG).to_dict()

    def test_before_and_after_is_explained(self):
        before, after = ev(SKILLS_ONLY), ev(STRONG)
        sim = simulate(before, after, ["Rewrote three bullets"])
        assert sim["scores"]["ats_match"]["after"] > sim["scores"]["ats_match"]["before"]
        assert "python" in [t.lower() for t in sim["requirements_improved"]]

    def test_a_strong_demonstrated_match_can_reach_the_top_bands(self):
        assert ev(STRONG).ats_match >= 70


class TestStructure:
    def test_roles_dates_and_evidence_lines_are_found(self):
        st = analyse(parse_resume_text(STRONG))
        assert len(st.roles) == 1 and st.roles[0].start and st.roles[0].end
        assert len(st.evidence) == 5 and st.total_years >= 5
        assert assess(st, extract_requirements(JD, "Senior Data Scientist"))


@pytest.mark.parametrize("text", [STRONG, SKILLS_ONLY, STUFFED, VARIANT, NO_SQL, JUNIOR])
def test_every_fixture_evaluates_without_error(text):
    result = ev(text)
    assert 0 <= result.ats_match <= 100 and 0 <= result.shortlist <= 100 and 0 <= result.parsing <= 100
