"""Suppression: when shortening cannot make Education and Work fit one page, the bullets that add
least to the job are removed, and nothing else is touched.

Real PDFs, real analysis, real re-flow; only the language model (not needed here) is absent.
"""

from __future__ import annotations

from unittest.mock import patch

from app.core.resume_tailoring import pdf_suppress
from app.core.resume_tailoring.evidence import AtsScore
from app.core.resume_tailoring.jobspec import parse_job
from app.core.resume_tailoring.pdf_fit import fit_pagination
from app.core.resume_tailoring.pdf_layout import build_document
from app.core.resume_tailoring.pdf_paginate import analyse
from tests import pdf_tools
from tests.unit.test_pdf_pagination import make

JD = """Data Scientist

Requirements
Python and SQL
forecasting
A/B testing
statistics
"""


def _bullets(path) -> list[str]:
    return [ln.text for ln in build_document(str(path)).bullets()]


async def test_bullets_are_removed_when_the_page_cannot_otherwise_hold_the_section(tmp_path):
    src = make(tmp_path, "cut", jobs=4)
    assert not analyse(src).ok
    out = tmp_path / "fit.pdf"
    result = await fit_pagination(src, out, llm=None, spec=parse_job(JD, title="Data Scientist"))

    assert result.status == "suppressed", result.report
    after = analyse(out)
    assert after.ok, [r.detail for r in after.violations]
    assert result.suppressed
    text = pdf_tools.flat_text(out)
    original = pdf_tools.flat_text(src)
    # The fixture repeats the same bullets under every copy of a role, so compare counts.
    for fragment in {t[:40] for t in result.suppressed.values()}:
        gone = sum(1 for t in result.suppressed.values() if t[:40] == fragment)
        assert original.count(fragment) - text.count(fragment) == gone, fragment
    kept = _bullets(out)
    assert len(kept) == len(_bullets(src)) - len(result.suppressed)
    assert "Northwind Logistics" in text and "Brightside Retail" in text  # no heading is lost


async def test_every_role_keeps_at_least_one_bullet(tmp_path):
    src = make(tmp_path, "keep", jobs=4)
    doc = build_document(str(src))
    result = await fit_pagination(
        src, tmp_path / "fit.pdf", llm=None, spec=parse_job(JD, title="Data Scientist")
    )
    removed = set(result.suppressed)
    groups = pdf_suppress._groups(doc)
    for lid, group in groups.items():
        assert [g for g in group if g not in removed], f"{lid}: a heading was left with no bullet"


async def test_a_removal_that_would_cost_the_match_is_not_made(tmp_path):
    src = make(tmp_path, "floor", jobs=4)
    out = tmp_path / "fit.pdf"

    def base_then_worse(doc, spec, *_a, **_k):
        total = 60 if len(doc.bullets()) >= len(build_document(str(src)).bullets()) else 40
        return AtsScore(total, {}, {}, [], [], [], [])

    with patch.object(pdf_suppress, "score", base_then_worse):
        result = await fit_pagination(
            src, out, llm=None, spec=parse_job(JD, title="Data Scientist"), score_floor=82
        )
    assert result.status == "not_met" and not result.suppressed
    assert out.read_bytes() == src.read_bytes()
    assert "costing more than it saves" in result.report["suppress"]["outcome"]


async def test_without_a_posting_nothing_is_cut(tmp_path):
    src = make(tmp_path, "nospec", jobs=4)
    out = tmp_path / "fit.pdf"
    result = await fit_pagination(src, out, llm=None)
    assert result.status == "not_met" and out.read_bytes() == src.read_bytes()
