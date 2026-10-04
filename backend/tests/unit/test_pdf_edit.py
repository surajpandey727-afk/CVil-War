"""In-place PDF editing: the layout reader, the editor and the checker, on real PDF files.

Nothing here mocks a PDF. Every test builds a CV PDF, edits it, and then reads the resulting
*file* back — text, fonts and rendered pixels — because a PDF can hold exactly the right words
and still be visibly broken.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from app.core.resume_tailoring.model import LineKind
from app.core.resume_tailoring.pdf_check import check_edited_pdf
from app.core.resume_tailoring.pdf_edit import edit_pdf_in_place
from app.core.resume_tailoring.pdf_layout import build_document
from tests import pdf_tools
from tests.pdf_cv_factory import CONTENTS, STYLES, make_cv

COMBOS = list(itertools.product(STYLES, CONTENTS))


@pytest.fixture(scope="module")
def cv_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("cvs")


@pytest.fixture(scope="module")
def cvs(cv_dir):
    return {(s, c): make_cv(cv_dir / f"{s}__{c}.pdf", s, c) for s, c in COMBOS}


_pixels = pdf_tools.pixels


def _line(doc, fragment):
    return next(ln for ln in doc.bullets() if fragment in ln.text)


class TestLayoutReader:
    @pytest.mark.parametrize(("style", "content"), COMBOS)
    def test_sections_bullets_and_summary_are_found(self, cvs, style, content):
        doc = build_document(str(cvs[(style, content)]))
        cv = CONTENTS[content]

        headings = [s.heading.upper() for s in doc.sections if s.heading]
        assert headings == ["SKILLS", "EXPERIENCE", "EDUCATION", "CERTIFICATIONS"]
        bullets = [ln for ln in doc.bullets() if ln.kind is LineKind.BULLET]
        expected_bullets = sum(len(job[3]) for job in cv.jobs) + len(cv.certifications)
        assert len(bullets) == expected_bullets
        prose = [ln for ln in doc.bullets() if ln.kind is LineKind.PROSE]
        assert len(prose) == 1 and prose[0].text.startswith(cv.summary[:30])

    @pytest.mark.parametrize(("style", "content"), COMBOS)
    def test_employers_titles_and_dates_are_never_editable(self, cvs, style, content):
        doc = build_document(str(cvs[(style, content)]))
        editable = {ln.text for ln in doc.bullets()}
        for employer, _title, dates, _ in CONTENTS[content].jobs:
            assert not any(employer in text or dates in text for text in editable)

    def test_wrapped_bullet_is_one_paragraph(self, cvs):
        doc = build_document(str(cvs[("serif_teal", "data_scientist")]))
        line = _line(doc, "demand forecasting model")
        assert len(doc.layout[line.id].lines) >= 2
        assert line.text.endswith("spreadsheet process.")

    def test_ligatures_are_expanded_to_letters(self, cvs):
        doc = build_document(str(cvs[("serif_teal", "data_scientist")]))
        text = doc.to_text()
        assert "Airflow" in text and "five" in text
        assert not any(ch in text for ch in "ﬁﬂﬀﬃﬄ")


class TestInvisibleRewrite:
    """Rewriting a paragraph with its own text must change nothing a reader could see."""

    @pytest.mark.parametrize(("style", "content"), COMBOS)
    def test_every_editable_paragraph_survives_a_round_trip(self, cvs, cv_dir, style, content):
        src = cvs[(style, content)]
        original = build_document(str(src))
        same = {ln.id: ln.text for ln in original.bullets()}
        out = cv_dir / f"ident__{style}__{content}.pdf"

        result = edit_pdf_in_place(src, original, same, out)
        check = check_edited_pdf(src, out, original, same, result)
        reread = build_document(str(out))

        assert result.skipped == [], [o.reason for o in result.skipped]
        assert check.ok, check.problems
        assert check.metrics["pixels_changed_outside_edits"] == 0
        assert reread.fingerprint() == original.fingerprint()
        assert [(ln.kind, ln.text) for ln in reread.all_lines()] == [
            (ln.kind, ln.text) for ln in original.all_lines()
        ]


class TestEdits:
    def test_edit_is_readable_replaced_text_is_gone_and_style_is_kept(self, cvs, cv_dir):
        src = cvs[("serif_teal", "data_scientist")]
        original = build_document(str(src))
        line = _line(original, "demand forecasting model")
        new_text = line.text.replace("Built a demand forecasting model", "Developed a demand forecasting model")
        out = cv_dir / "edit1.pdf"

        result = edit_pdf_in_place(src, original, {line.id: new_text}, out)
        check = check_edited_pdf(src, out, original, {line.id: new_text}, result)

        assert check.ok, check.problems
        page_text = pdf_tools.raw_text(out)
        assert "Developed a demand forecasting model" in page_text.replace("\n", " ")
        assert "Built a demand forecasting model" not in page_text.replace("\n", " ")
        par = original.layout[line.id]
        rect = (par.bbox[0] - 1, par.bbox[1] - 1, par.bbox[2] + 1, par.bbox[3] + 1)
        before = pdf_tools.styles_in(src, par.page, rect)
        after = pdf_tools.styles_in(out, par.page, rect)
        assert after <= before

    def test_other_paragraphs_are_left_exactly_alone(self, cvs, cv_dir):
        src = cvs[("sans_plain", "business_analyst")]
        original = build_document(str(src))
        line = _line(original, "user stories")
        out = cv_dir / "edit2.pdf"
        edit_pdf_in_place(src, original, {line.id: line.text.replace("four sprints", "4 sprints")}, out)

        reread = build_document(str(out))
        others_before = [(ln.id, ln.text) for ln in original.all_lines() if ln.id != line.id]
        others_after = [(ln.id, ln.text) for ln in reread.all_lines() if ln.id != line.id]
        assert others_before == others_after

    def test_hyphens_and_spaces_extract_as_themselves(self, cvs, cv_dir):
        # An embedded subset can map the hyphen glyph onto a soft hyphen and the space onto a
        # no-break space. Either would reach an ATS as a corrupted keyword.
        src = cvs[("serif_teal", "data_scientist")]
        original = build_document(str(src))
        line = _line(original, "batch scoring pipelines")
        new_text = line.text.replace("Productionised", "Productionised cloud-native")
        out = cv_dir / "edit3.pdf"
        edit_pdf_in_place(src, original, {line.id: new_text}, out)

        page_text = pdf_tools.raw_text(out)
        assert "cloud-native batch" in page_text.replace(chr(10), " ")
        assert chr(0xA0) not in page_text and chr(0xAD) not in page_text

    def test_justified_paragraph_stays_justified(self, cvs, cv_dir):
        src = cvs[("serif_teal", "data_scientist")]
        original = build_document(str(src))
        summary = next(ln for ln in original.bullets() if ln.kind is LineKind.PROSE)
        out = cv_dir / "edit4.pdf"
        new_text = summary.text.replace("mentor junior analysts", "mentor junior staff")
        result = edit_pdf_in_place(src, original, {summary.id: new_text}, out)
        assert result.applied, [o.reason for o in result.skipped]

        reread = build_document(str(out))
        paragraph = reread.layout[next(ln.id for ln in reread.bullets() if ln.kind is LineKind.PROSE)]
        edges = [ln.body_x1 for ln in paragraph.lines[:-1]]
        assert max(edges) - min(edges) < 1.5

    def test_an_edit_that_needs_another_line_is_skipped_not_forced(self, cvs, cv_dir):
        src = cvs[("serif_teal", "data_scientist")]
        original = build_document(str(src))
        line = _line(original, "Mentored 3 junior analysts")
        too_long = line.text + " " + "Additional wording that cannot possibly fit on the same line. " * 3
        out = cv_dir / "edit5.pdf"

        result = edit_pdf_in_place(src, original, {line.id: too_long}, out)

        assert [o.status for o in result.outcomes] == ["skipped"]
        assert "lines" in result.skipped[0].reason
        assert np.array_equal(_pixels(src), _pixels(out))

    def test_a_character_no_font_can_draw_is_skipped(self, cvs, cv_dir):
        src = cvs[("sans_plain", "data_scientist")]
        original = build_document(str(src))
        line = _line(original, "Mentored 3 junior analysts")
        out = cv_dir / "edit6.pdf"
        result = edit_pdf_in_place(src, original, {line.id: line.text.replace("Mentored", "Mentored 导师")}, out)
        assert result.skipped and "no available font" in result.skipped[0].reason

    def test_edits_on_different_pages_or_paragraphs_do_not_interfere(self, cvs, cv_dir):
        src = cvs[("serif_navy_small", "product_manager")]
        original = build_document(str(src))
        a = _line(original, "invoicing product roadmap")
        b = _line(original, "customer discovery")
        edits = {
            a.id: a.text.replace("Owned the invoicing", "Led the invoicing"),
            b.id: b.text.replace("Ran customer discovery", "Ran customer research"),
        }
        out = cv_dir / "edit7.pdf"
        result = edit_pdf_in_place(src, original, edits, out)
        check = check_edited_pdf(src, out, original, edits, result)
        assert len(result.applied) == 2 and check.ok, check.problems


class TestChecker:
    def _identity(self, cvs, cv_dir, name):
        src = cvs[("sans_green", "product_manager")]
        original = build_document(str(src))
        edits = {ln.id: ln.text for ln in original.bullets()[:2]}
        out = cv_dir / f"{name}.pdf"
        return src, original, edits, out, edit_pdf_in_place(src, original, edits, out)

    def test_an_unopenable_file_fails_the_check(self, cvs, cv_dir):
        src, original, edits, out, result = self._identity(cvs, cv_dir, "chk0")
        out.write_bytes(b"%PDF-1.4 definitely not a pdf")
        assert not check_edited_pdf(src, out, original, edits, result).ok

    def test_a_changed_page_count_fails_the_check(self, cvs, cv_dir):
        src, original, edits, out, result = self._identity(cvs, cv_dir, "chk1")
        pdf_tools.with_extra_page(out, cv_dir / "chk1b.pdf")
        check = check_edited_pdf(src, cv_dir / "chk1b.pdf", original, edits, result)
        assert not check.ok and "page count" in check.problems[0]

    def test_text_lost_outside_the_edits_fails_the_check(self, cvs, cv_dir):
        src, original, edits, out, result = self._identity(cvs, cv_dir, "chk2")
        victim = _line(original, "Defined success metrics")
        damaged = out
        for index, para_line in enumerate(original.layout[victim.id].lines):
            damaged = pdf_tools.with_text_removed(damaged, cv_dir / f"chk2b{index}.pdf", para_line)
        check = check_edited_pdf(src, damaged, original, edits, result)
        assert not check.ok
        assert any("outside the edited" in p or "lost" in p for p in check.problems)

    def test_overlapping_text_fails_the_check(self, cvs, cv_dir):
        src, original, edits, out, result = self._identity(cvs, cv_dir, "chk3")
        target = original.layout[next(iter(edits))].lines[0]
        pdf_tools.with_overlaid_text(out, cv_dir / "chk3b.pdf", target.page, target.body_x0 + 5, target.baseline, "OVERLAPPING WORDS HERE")
        check = check_edited_pdf(src, cv_dir / "chk3b.pdf", original, edits, result)
        assert not check.ok


class TestPagination:
    def test_headings_and_separators_are_reported_and_unchanged(self, cvs, cv_dir):
        src = cvs[("serif_teal", "data_scientist")]
        original = build_document(str(src))
        line = _line(original, "demand forecasting model")
        edits = {line.id: line.text.replace("Built", "Developed")}
        out = cv_dir / "pag1.pdf"
        result = edit_pdf_in_place(src, original, edits, out)
        check = check_edited_pdf(src, out, original, edits, result)

        assert check.ok, check.problems
        pagination = check.metrics["pagination"]
        assert pagination["separators_unchanged"] and pagination["section_starts_unchanged"]
        assert set(pagination["section_pages"]) == {"SKILLS", "EXPERIENCE", "EDUCATION", "CERTIFICATIONS"}
        assert all(page == 1 for page in pagination["section_pages"].values())
        assert pagination["separators_per_page"] == [4]

    def test_a_displaced_separator_fails_the_check(self, cvs, cv_dir):
        src = cvs[("serif_teal", "data_scientist")]
        original = build_document(str(src))
        line = _line(original, "demand forecasting model")
        edits = {line.id: line.text.replace("Built", "Developed")}
        out = cv_dir / "pag2.pdf"
        result = edit_pdf_in_place(src, original, edits, out)
        pdf_tools.with_rule(out, cv_dir / "pag2b.pdf", 0, 700)  # a stray rule where none belongs
        check = check_edited_pdf(src, cv_dir / "pag2b.pdf", original, edits, result)
        assert not check.ok and any("separator" in p for p in check.problems)

    def test_the_first_separator_stays_on_page_one_of_a_multi_page_cv(self, cv_dir):
        # A CV long enough to run onto a second page: edits must not drag its rules across.
        from tests.pdf_cv_factory import CONTENTS, CvContent

        base = CONTENTS["product_manager"]
        long_cv = CvContent(
            base.person, base.contact, base.summary, base.skills,
            base.jobs * 4, base.education, base.certifications,
        )
        CONTENTS["_long"] = long_cv
        try:
            src = make_cv(cv_dir / "long.pdf", "serif_teal", "_long")
            assert pdf_tools.page_count(src) >= 2
            original = build_document(str(src))
            line = _line(original, "Defined success metrics")
            edits = {line.id: line.text.replace("at the verification step.", "at the verification step with analytics.")}
            out = cv_dir / "long_out.pdf"
            result = edit_pdf_in_place(src, original, edits, out)
            check = check_edited_pdf(src, out, original, edits, result)
            assert check.ok, check.problems
            counts = [len(pdf_tools.rules_on(out, i)) for i in range(pdf_tools.page_count(out))]
            assert next(i for i, n in enumerate(counts) if n) == 0
            assert check.metrics["pagination"]["separators_per_page"] == counts
        finally:
            CONTENTS.pop("_long", None)
