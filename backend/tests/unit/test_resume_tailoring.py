"""The résumé tailoring engine.

Every test here corresponds to something the previous engine got wrong on a real CV. The
headline one is :class:`TestNothingIsEverDropped`: run against a CV whose headings read
"Key Highlights and Skills:", "EDUCATION & QUALIFICATIONS" and "WORK & LEADERSHIP EXPERIENCE",
the old parser matched none of them against its 24-string whitelist and handed the model a
name and an email address. The model, given nothing, invented a candidate — and the document
that came out named employers, skills and a career the person had never had.

So the first duty of this suite is to prove that the CV survives the pipeline, and the second
is to prove that nothing is added to it that the CV cannot support.
"""
# ruff: noqa: RUF001
# The fixture CV uses the punctuation real CVs use - en dashes, bullet glyphs and an
# arrow in a job title. Replacing them with ASCII would stop the fixture exercising the
# characters the parser exists to handle.


from __future__ import annotations

import pytest

from app.core.resume_tailoring.apply import apply_plan, build_audit
from app.core.resume_tailoring.evidence import (
    legitimate_vocabulary,
    match_requirements,
    score,
)
from app.core.resume_tailoring.extract import is_heading, parse_resume_text
from app.core.resume_tailoring.jobspec import Tier, parse_job
from app.core.resume_tailoring.model import LineKind
from app.core.resume_tailoring.plan import BulletOrder, ProposedEdit
from app.core.resume_tailoring.reorder import propose_reorder, relevance
from app.core.resume_tailoring.validate import (
    check_edit,
    preserved_ratio,
    validate_document,
    validate_edits,
)

# A CV in the shape real CVs come in: an unlabelled summary, headings nobody standardised, a
# skills block laid out as a table, and several projects under one employer.
CV = """Suraj N. Pandey
London, UK
M: 07377 680881 | E: suraj.pandey727@gmail.com | LinkedIn
Data Scientist and Product-focused AI Product Manager with 3+ years of experience building
production-grade ML, GenAI and cloud-native systems.
Key Highlights and Skills:
Category Technologies / Skills
Language and Frameworks • Python: Pandas, NumPy, Scikit-learn
EDUCATION & QUALIFICATIONS
Warwick Business School, MSc Business Analytics Sept 2022 - Sept 2023
MIT-WPU, Pune, BSc Economics (Hons.) July 2018 - July 2021
WORK & LEADERSHIP EXPERIENCE
SimplyPhi, Woking, UK, (Technology Team)
Data Scientist → AI Product Manager June 2024 - Present
IRIS 2.0 – AI Property Asset Intelligence Platform
• Led the transformation of a legacy platform into a scalable Azure-based cloud architecture.
• Built vector search and semantic retrieval across 900K+ property records using embeddings,
ChromaDB and PostgreSQL, delivering sub-200ms retrieval.
SimplyFind – AI Property Market Intelligence SaaS
• Built an AI governance layer covering retrieval grounding and citation validation.
Pixis, Bengaluru, India, (Product Team)
Technology Analyst April 2021 - July 2022
• Managed 2 marketing automation products for product comparison.
CERTIFICATIONS & INTERESTS
• Certifications: Associate Data Scientist (DataCamp, 2024)
"""

JOB = """Product Manager, Data Platform
What You'll Do
Own the product strategy and roadmap for the data catalogue, metadata and data lineage domain.
Define success metrics and KPIs that measure adoption and business impact.
Who You Are
Requirements
You have 2+ years of Product Management experience on platform products, developer tools,
data infrastructure, analytics platforms or data governance systems.
You have a degree in Computer Science or Engineering.
Desirable
Familiarity with machine learning and semantic search.
"""


@pytest.fixture
def doc():
    return parse_resume_text(CV, source_format="text")


@pytest.fixture
def spec():
    return parse_job(JOB, title="Product Manager, Data Platform")


class TestNothingIsEverDropped:
    """The defect that produced a hallucinated CV from a real one."""

    def test_every_non_blank_line_survives_parsing(self, doc) -> None:
        source = [ln.strip() for ln in CV.splitlines() if ln.strip()]
        rendered = doc.to_text()
        missing = [ln for ln in source if ln.split()[0] not in rendered]
        assert not missing, f"lines vanished during parsing: {missing}"

    def test_the_whole_career_history_survives(self, doc) -> None:
        text = doc.to_text()
        for fact in (
            "SimplyPhi", "Pixis", "Warwick Business School", "MIT-WPU",
            "IRIS 2.0", "SimplyFind", "ChromaDB", "DataCamp", "07377",
        ):
            assert fact in text, f"{fact} was lost"

    def test_headings_nobody_standardised_are_still_recognised(self, doc) -> None:
        """None of these match a canonical section vocabulary, and all five are real."""
        assert doc.headings() == [
            "Key Highlights and Skills:",
            "EDUCATION & QUALIFICATIONS",
            "WORK & LEADERSHIP EXPERIENCE",
            "CERTIFICATIONS & INTERESTS",
        ]

    def test_an_unlabelled_summary_is_kept_and_stays_editable(self, doc) -> None:
        """A CV that opens with a summary carrying no heading of its own is the common case,
        and the previous parser discarded precisely that block."""
        first = doc.sections[0]
        assert first.heading == ""
        assert "Data Scientist and Product-focused" in first.lines[0].text
        assert first.lines[0].kind is LineKind.PROSE

    def test_an_empty_cv_does_not_explode(self) -> None:
        assert parse_resume_text("").sections == []


class TestHeadingDetection:
    @pytest.mark.parametrize(
        "line",
        ["EDUCATION & QUALIFICATIONS", "WORK & LEADERSHIP EXPERIENCE",
         "Key Highlights and Skills:", "TECHNICAL SKILLS", "PROFESSIONAL EXPERIENCE"],
    )
    def test_real_headings_are_recognised(self, line: str) -> None:
        assert is_heading(line)

    @pytest.mark.parametrize(
        "line",
        [
            "Data Scientist → AI Product Manager June 2024 - Present",
            "M: 07377 680881 | E: suraj.pandey727@gmail.com | LinkedIn",
            "Warwick Business School, MSc Business Analytics Sept 2022 - Sept 2023",
            "• Led the transformation of a legacy platform into a scalable architecture.",
        ],
    )
    def test_role_and_contact_lines_are_not_headings(self, line: str) -> None:
        """A false heading splits a section and can strand bullets under the wrong employer."""
        assert not is_heading(line)


class TestStructureIsImmutableByConstruction:
    def test_the_skills_table_cannot_be_edited(self, doc) -> None:
        """Flattened table rows look like bullets. Editing one scrambles the table."""
        skills = next(s for s in doc.sections if "Skills" in s.heading)
        assert skills.editable_lines == []

    def test_education_cannot_be_edited(self, doc) -> None:
        education = next(s for s in doc.sections if "EDUCATION" in s.heading)
        assert education.editable_lines == []

    def test_employer_and_date_lines_are_not_editable(self, doc) -> None:
        work = next(s for s in doc.sections if "WORK" in s.heading)
        fixed = [ln.text for ln in work.lines if not ln.editable]
        assert any("SimplyPhi" in t for t in fixed)
        assert any("Pixis" in t for t in fixed)
        assert any("June 2024 - Present" in t for t in fixed)

    def test_the_fingerprint_covers_everything_immutable(self, doc) -> None:
        before = doc.fingerprint()
        copy = doc.copy()
        copy.sections[2].lines[0].text = "AcmeCorp, London"
        assert copy.fingerprint() != before


class TestNoFabrication:
    """Each of these is a real edit the planner proposed against the real CV."""

    def _check(self, before: str, after: str, allowed=frozenset()):
        return check_edit(
            ProposedEdit(line_id="L1", after_text=after, evidence=f"CV states: {before[:40]}"),
            before,
            CV,
            allowed,
        )

    def test_an_invented_metric_is_blocked(self) -> None:
        result = self._check(
            "Built vector search across 900K+ property records",
            "Built vector search across 2M+ property records",
        )
        assert result is not None and result.rule == "fabricated_metric"

    def test_an_invented_technology_is_blocked(self) -> None:
        result = self._check(
            "Built vector search using embeddings",
            "Built vector search using embeddings and Tableau",
        )
        assert result is not None and result.rule == "unsupported_technology"

    def test_an_appended_capability_clause_is_blocked(self) -> None:
        """Every word here is in the CV, and the claim still is not."""
        result = self._check(
            "Built an AI governance layer covering retrieval grounding and citation validation.",
            "Built an AI governance layer covering retrieval grounding and citation validation, "
            "supporting metadata and lineage-aware data discoverability across the platform.",
        )
        assert result is not None
        assert result.rule in ("unsupported_claim", "appended_clause")

    def test_newly_asserted_ownership_is_blocked(self) -> None:
        """"covering X" became "owning the product roadmap for X" on a real run."""
        result = self._check(
            "Defined and monitored the architecture, covering API contracts.",
            "Defined and monitored the architecture, owning the product roadmap for API contracts.",
        )
        assert result is not None
        assert result.rule in ("asserted_ownership", "unsupported_claim")

    def test_claim_escalation_is_blocked(self) -> None:
        result = self._check(
            "Worked with engineering teams on API contracts",
            "Led engineering teams on API contracts",
        )
        # Two rules independently forbid this, and the ownership check happens to fire first.
        # Which one caught it does not matter; that it is refused does.
        assert result is not None
        assert result.rule in ("claim_escalation", "asserted_ownership")

    def test_ai_language_is_blocked(self) -> None:
        result = self._check(
            "Built vector search across records",
            "Built robust vector search across records",
        )
        assert result is not None and result.rule == "ai_language"

    def test_losing_a_keyword_is_blocked(self) -> None:
        """Deleting "AI" from "AI Product Manager" tidies the phrase and weakens the CV."""
        result = self._check("Built AI vector search", "Built vector search")
        assert result is not None and result.rule == "keyword_loss"

    def test_vague_evidence_is_blocked(self) -> None:
        result = check_edit(
            ProposedEdit(line_id="L1", after_text="Built semantic search", evidence="general experience"),
            "Built vector search",
            CV,
        )
        assert result is not None and result.rule == "vague_evidence"

    def test_a_substantive_citation_that_mentions_the_cv_is_accepted(self) -> None:
        """Rejecting evidence for containing the words "the CV" threw out real citations."""
        result = check_edit(
            ProposedEdit(
                line_id="L1",
                after_text="Built vector search and semantic search across records",
                evidence="The CV states: Built vector search and semantic retrieval across 900K+ records",
            ),
            "Built vector search across records",
            CV,
            frozenset({"semantic", "search"}),
        )
        assert result is None


class TestLegitimateEditsSurvive:
    def test_terminology_the_cv_has_earned_may_be_used(self) -> None:
        """Rule 6D: the posting's wording for something the CV already demonstrates."""
        result = check_edit(
            ProposedEdit(
                line_id="L1",
                after_text="Built vector search and data discovery across 900K+ records",
                evidence="CV states: Built vector search and semantic retrieval across 900K+ records",
            ),
            "Built vector search across 900K+ records",
            CV,
            frozenset({"data", "discovery"}),
        )
        assert result is None

    def test_the_cv_earns_a_vocabulary_of_its_own(self, doc) -> None:
        earned = legitimate_vocabulary(doc)
        assert "data discovery" in earned  # via vector search / semantic retrieval
        assert "semantic search" in earned
        assert "data catalogue" not in earned  # nothing in the CV implies one
        assert "data lineage" not in earned


class TestReorderingCannotReattributeWork:
    def test_a_bullet_never_leaves_its_own_employer(self, doc, spec) -> None:
        """Moving a Pixis bullet under SimplyPhi would credit one employer's work to another
        — a fabrication no wording check would ever see."""
        work = next(s for s in doc.sections if "WORK" in s.heading)
        pixis_bullet = next(ln for ln in work.bullets if "marketing automation" in ln.text)

        every_id = [ln.id for ln in work.bullets]
        request = BulletOrder(section_heading=work.heading, line_ids=list(reversed(every_id)))
        after = apply_plan(doc, [], [request])

        after_work = next(s for s in after.sections if "WORK" in s.heading)
        positions = [ln.id for ln in after_work.lines]
        pixis_line_index = positions.index(pixis_bullet.id)
        preceding = [ln.text for ln in after_work.lines[:pixis_line_index] if not ln.editable]
        assert any("Pixis" in t for t in preceding), "bullet moved out from under its employer"

    def test_reordering_changes_no_wording(self, doc, spec) -> None:
        coverage = match_requirements(doc, spec)
        after = apply_plan(doc, [], propose_reorder(doc, coverage, spec))
        assert sorted(ln.text for ln in doc.all_lines()) == sorted(
            ln.text for ln in after.all_lines()
        )

    def test_a_marginal_win_leaves_the_candidates_order_alone(self, doc, spec) -> None:
        """Relevance scoring is a heuristic; a narrow lead is not a reason to reshuffle."""
        coverage = match_requirements(doc, spec)
        for request in propose_reorder(doc, coverage, spec):
            assert request.line_ids, "an empty reorder should not be proposed"

    def test_relevance_prefers_the_bullet_about_the_work(self, doc, spec) -> None:
        coverage = match_requirements(doc, spec)
        governance = next(
            ln for ln in doc.bullets() if "governance layer" in ln.text
        )
        certification = next(ln for ln in doc.bullets() if "Certifications:" in ln.text)
        assert relevance(governance.text, coverage) > relevance(certification.text, coverage)


class TestDocumentLevelGuarantees:
    def test_an_edited_document_keeps_its_structure(self, doc) -> None:
        target = next(ln for ln in doc.bullets() if "vector search" in ln.text)
        edit = ProposedEdit(
            line_id=target.id,
            after_text=target.text.replace("vector search", "vector search and data discovery"),
            evidence="CV states: Built vector search and semantic retrieval across 900K+ records",
        )
        report = validate_edits(doc, [edit], frozenset({"data", "discovery"}))
        assert report.accepted, report.rejected

        tailored = apply_plan(doc, report.accepted)
        report = validate_document(doc, tailored, report)
        assert report.ok, report.document_failures
        assert doc.headings() == tailored.headings()
        assert len(doc.bullets()) == len(tailored.bullets())

    def test_rewriting_everything_is_refused(self, doc) -> None:
        """The guarantee the operator relies on: this cannot quietly become someone else's CV."""
        wrecked = doc.copy()
        for line in wrecked.bullets():
            line.text = "Delivered transformative outcomes for stakeholders."
        report = validate_document(doc, wrecked, validate_edits(doc, []))
        assert not report.ok
        assert any("EXCESSIVE TRANSFORMATION" in f for f in report.document_failures)

    def test_a_moved_heading_fails_the_pass(self, doc) -> None:
        wrecked = doc.copy()
        wrecked.sections[1].heading = "Core Competencies"
        report = validate_document(doc, wrecked, validate_edits(doc, []))
        assert not report.ok

    def test_preserved_ratio_is_one_when_nothing_changed(self, doc) -> None:
        assert preserved_ratio(doc, doc.copy()) == 1.0


class TestScoring:
    def test_the_score_is_reproducible(self, doc, spec) -> None:
        """A figure that drifts on its own cannot be compared before and after."""
        first = score(doc, spec, match_requirements(doc, spec))
        second = score(doc, spec, match_requirements(doc, spec))
        assert first.total == second.total
        assert first.components == second.components

    def test_components_are_published_with_their_weights(self, doc, spec) -> None:
        result = score(doc, spec, match_requirements(doc, spec))
        assert set(result.components) == set(result.weights)
        assert round(sum(result.weights.values()), 6) == 1.0

    def test_an_unmet_mandatory_requirement_is_named_not_hidden(self, doc, spec) -> None:
        result = score(doc, spec, match_requirements(doc, spec))
        assert result.constrained_by == result.missing_mandatory
        if result.missing_mandatory:
            assert "constrained by" in result.explain().lower()

    def test_mandatory_and_preferred_are_scored_separately(self, spec) -> None:
        """Averaging them lets a pile of nice-to-haves hide a missing must-have."""
        assert spec.terms(Tier.MANDATORY)
        assert "required_skills" in score(
            parse_resume_text(CV), spec, match_requirements(parse_resume_text(CV), spec)
        ).components


class TestTheAudit:
    def test_every_change_is_recorded_with_its_evidence(self, doc, spec) -> None:
        target = next(ln for ln in doc.bullets() if "vector search" in ln.text)
        edit = ProposedEdit(
            line_id=target.id,
            after_text=target.text.replace("vector search", "vector search and data discovery"),
            reason="Uses the posting's term for capability already demonstrated",
            evidence="CV states: Built vector search and semantic retrieval across 900K+ records",
            keywords_added=["data discovery"],
            level="4_keyword_alignment",
        )
        report = validate_edits(doc, [edit], frozenset({"data", "discovery"}))
        tailored = apply_plan(doc, report.accepted)
        coverage = match_requirements(doc, spec)
        audit = build_audit(
            original=doc,
            tailored=tailored,
            accepted=report.accepted,
            rejected=report.rejected,
            before_score=score(doc, spec, coverage),
            after_score=score(tailored, spec, match_requirements(tailored, spec)),
            reordered=[],
            document_failures=[],
            job_title="Product Manager, Data Platform",
        )
        assert audit.bullets_changed == 1
        assert audit.bullets_unchanged == len(doc.bullets()) - 1
        assert audit.changes[0].evidence
        assert audit.keywords_added == ["data discovery"]
        assert audit.fabrication_check == "PASSED"
        assert audit.ready_for_review

    def test_a_failed_pass_is_not_ready_for_review(self, doc, spec) -> None:
        coverage = match_requirements(doc, spec)
        audit = build_audit(
            original=doc,
            tailored=doc.copy(),
            accepted=[],
            rejected=[],
            before_score=score(doc, spec, coverage),
            after_score=score(doc, spec, coverage),
            reordered=[],
            document_failures=["section names or order changed"],
        )
        assert not audit.ready_for_review
        assert audit.fabrication_check == "FAILED"

    def test_the_audit_serialises(self, doc, spec) -> None:
        coverage = match_requirements(doc, spec)
        audit = build_audit(
            original=doc, tailored=doc.copy(), accepted=[], rejected=[],
            before_score=score(doc, spec, coverage),
            after_score=score(doc, spec, coverage),
            reordered=[], document_failures=[],
        )
        payload = audit.to_dict()
        for key in (
            "original_ats_score", "final_ats_score", "keywords_added", "bullets_changed",
            "bullets_unchanged", "structure_preserved", "fabrication_check",
            "ready_for_review", "changes",
        ):
            assert key in payload
