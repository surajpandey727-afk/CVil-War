# PDF stack: licences

The tailored-résumé pipeline (`backend/app/core/resume_tailoring/pdf_*`) reads, edits, re-flows and
renders PDFs. **No component of it is copyleft.** An earlier version used PyMuPDF, which is
AGPL-3.0 (or commercial); it has been removed, and nothing in the project depends on it.

| Job | Library | Licence |
|---|---|---|
| Glyph geometry, fonts and rules per page | `pdfplumber` (on `pdfminer.six`) | MIT |
| Opening, cloning and writing PDF files; content-stream objects | `pypdf` | BSD-3-Clause |
| Rendering pages to pixels for visual comparison | `pypdfium2` (PDFium) | Apache-2.0 / BSD-3-Clause |
| Subsetting and reading font programs | `fonttools` | MIT |
| Standard-font metrics (Times, Helvetica, Courier) | `reportlab` | BSD |
| Pixel arithmetic | `numpy` | BSD-3-Clause |

The content-stream parser, text-state interpreter, glyph remover, atom splitter, re-flow engine and
pagination analyser are this project's own code (`pdf_stream.py`, `pdf_atoms.py`, `pdf_reflow.py`,
`pdf_paginate.py`).

Verified against the installed environment: no installed distribution declares an AGPL or Affero
licence. Re-check when adding a PDF dependency:

```bash
cd backend && uv run python -c "from importlib.metadata import distributions as d; print([x.metadata['Name'] for x in d() if 'agpl' in ' '.join([x.metadata.get('License') or '', *(x.metadata.get_all('Classifier') or [])]).lower()])"
```

Fonts: replacement glyphs are drawn from the document's own embedded fonts first, then from fonts
installed on the host (Windows system fonts, or Liberation / Carlito on Linux), then the 14 standard
faces, which every viewer provides. Installed fonts are embedded only as subsets of the glyphs used.
