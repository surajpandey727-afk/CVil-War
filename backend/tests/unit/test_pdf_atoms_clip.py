"""A table cell that clips its text (as Word draws a skills table) must not stop a page being moved.

Each atom drawn under a clip window carries that window and moves it with the atom; a window the
size of the page is no window at all. Pages the splitter still cannot take apart are left alone
when nothing on them moves.
"""

from __future__ import annotations

from pypdf import PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.core.resume_tailoring import pdf_atoms as pa
from app.core.resume_tailoring import pdf_stream as ps
from app.core.resume_tailoring.pdf_reflow import _page_atoms


def _clipped_pdf(path):
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 10)
    # whole-page clip, then a small cell clip around the second line
    page = c.beginPath()
    page.rect(0, 0, 612, 792)
    c.saveState()
    c.clipPath(page, stroke=0, fill=0)
    c.drawString(50, 700, "Outside any cell")
    c.restoreState()
    cell = c.beginPath()
    cell.rect(40, 640, 200, 30)
    c.saveState()
    c.clipPath(cell, stroke=0, fill=0)
    c.drawString(50, 650, "Python: Pandas, NumPy")
    c.restoreState()
    c.save()
    return path


def _atoms(path):
    writer = PdfWriter(clone_from=str(path))
    return _page_atoms(writer, 0)


def test_text_under_a_cell_clip_is_an_atom_that_carries_its_window(tmp_path):
    atoms = [a for a in _atoms(_clipped_pdf(tmp_path / "c.pdf")) if a.kind == "text"]
    assert len(atoms) == 2
    plain, clipped = min(atoms, key=lambda a: a.top), max(atoms, key=lambda a: a.top)
    names = [o.operator for o in clipped.ops]
    assert not any(o.operator.startswith("W") for o in plain.ops), "a page-sized clip is dropped"
    clip_at = next(i for i, n in enumerate(names) if n.startswith("W"))
    assert clip_at < names.index("BT")


def test_moving_an_atom_moves_its_clip_window_with_it(tmp_path):
    clipped = next(a for a in _atoms(_clipped_pdf(tmp_path / "c.pdf")) if any(o.operator.startswith("W") for o in a.ops))
    window = next(o for o in clipped.ops if o.operator == "re")
    moved = pa.shifted(clipped, 100.0)  # 100pt lower on the page
    new_window = next(o for o in moved if o.operator == "re")
    assert float(new_window.operands[1]) == float(window.operands[1]) - 100.0
    assert float(new_window.operands[3]) == float(window.operands[3])  # same size
    tm = next(o for o in moved if o.operator == "Tm")
    old_tm = next(o for o in clipped.ops if o.operator == "Tm")
    assert float(tm.operands[5]) == float(old_tm.operands[5]) - 100.0
    assert isinstance(ps.join(moved), bytes)
