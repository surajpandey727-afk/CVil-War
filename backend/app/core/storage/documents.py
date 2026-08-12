"""Bridge generated documents into per-tenant storage.

The document generator renders to local temp paths; these helpers move the bytes into the
tenant-scoped :class:`StorageService` (``users/{uid}/…``) and return the storage KEYS that
get persisted on the model (Resume/Application columns hold keys, not absolute paths).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from app.core.storage import StorageService, get_storage, keys

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def persist_generated_document(user_id: str, doc: Any) -> tuple[str | None, str | None]:
    """Move a generated doc's rendered PDF/DOCX into storage; return (pdf_key, docx_key).

    The temp render files are removed once copied. ``doc`` is a GeneratedDocument
    (``type``, ``document_id``, ``pdf_path``, ``docx_path``).
    """
    storage = StorageService(get_storage(), user_id)
    key_fn = keys.cover_letter_key if doc.type == "cover_letter" else keys.resume_key
    pdf_key = docx_key = None
    if doc.pdf_path:
        pdf_key = key_fn(user_id, doc.document_id, "pdf")
        await storage.put(pdf_key, Path(doc.pdf_path).read_bytes(), content_type=PDF_CONTENT_TYPE)
        with contextlib.suppress(OSError):
            Path(doc.pdf_path).unlink()
    if doc.docx_path:
        docx_key = key_fn(user_id, doc.document_id, "docx")
        await storage.put(
            docx_key, Path(doc.docx_path).read_bytes(), content_type=DOCX_CONTENT_TYPE
        )
        with contextlib.suppress(OSError):
            Path(doc.docx_path).unlink()
    return pdf_key, docx_key
