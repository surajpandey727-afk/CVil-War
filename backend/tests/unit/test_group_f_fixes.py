"""Group F remediation regression tests: per-tenant document storage + pre-apply ATS gate."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.core.storage import documents
from app.core.storage.local import LocalFileStorage
from app.workers import tasks

# --- F2: generated documents land in per-tenant storage ---------------------


class TestPersistGeneratedDocument:
    async def test_moves_bytes_to_storage_and_removes_temp(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"PDFDATA")
        docx = tmp_path / "a.docx"
        docx.write_bytes(b"DOCXDATA")
        doc = MagicMock(type="resume", document_id="doc1", pdf_path=str(pdf), docx_path=str(docx))
        store = LocalFileStorage(str(tmp_path / "store"), "sig-secret")

        with patch.object(documents, "get_storage", return_value=store):
            pdf_key, docx_key = await documents.persist_generated_document("u1", doc)

        assert pdf_key == "users/u1/resumes/doc1.pdf"  # per-tenant prefixed key
        assert docx_key == "users/u1/resumes/doc1.docx"
        assert await store.get(pdf_key) == b"PDFDATA"  # bytes moved into storage
        assert await store.get(docx_key) == b"DOCXDATA"
        assert not pdf.exists() and not docx.exists()  # temp render files removed

    async def test_cover_letter_uses_cover_letter_prefix(self, tmp_path):
        pdf = tmp_path / "c.pdf"
        pdf.write_bytes(b"CL")
        doc = MagicMock(type="cover_letter", document_id="cl1", pdf_path=str(pdf), docx_path=None)
        store = LocalFileStorage(str(tmp_path / "store"), "sig-secret")

        with patch.object(documents, "get_storage", return_value=store):
            pdf_key, docx_key = await documents.persist_generated_document("u1", doc)

        assert pdf_key == "users/u1/cover_letters/cl1.pdf"
        assert docx_key is None


# --- F4: pre-apply ATS gate -------------------------------------------------


class TestAtsScoring:
    """``_ats_gate_ok`` used to decide as well as score, against a hardcoded threshold.

    The decision now belongs to :mod:`app.core.policy` and this function only reports a
    score. The behaviour that changed deliberately is the unscoreable case: it used to return
    ``(True, 0.0)`` and wave the application through, which meant an unavailable scorer
    silently made the threshold optional. It now reports ``None``, which the policy escalates
    — see ``tests/unit/test_policy_engine.py``.
    """

    async def test_no_resume_falls_back_to_the_score_recorded_at_discovery(self, db_session):
        app = MagicMock(resume_id=None, ats_score=0.82)
        assert await tasks._ats_score(db_session, app) == 0.82

    async def test_no_resume_and_no_stored_score_is_unscored_not_zero(self, db_session):
        app = MagicMock(resume_id=None, ats_score=None)
        assert await tasks._ats_score(db_session, app) is None

    async def test_a_live_score_is_returned_verbatim(self, db_session):
        app = MagicMock(resume_id="r1", job_id="j1", id="a1")
        with patch(
            "app.services.resume.score_resume",
            new=AsyncMock(return_value=MagicMock(overall_score=0.30)),
        ):
            assert await tasks._ats_score(db_session, app) == 0.30

    async def test_a_scoring_failure_falls_back_rather_than_inventing_a_number(
        self, db_session
    ):
        """Reporting 0.0 here would look like a genuine no-match and refuse the application
        for a reason that was never measured."""
        app = MagicMock(resume_id="r1", job_id="j1", id="a1", ats_score=None)
        with patch(
            "app.services.resume.score_resume", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            assert await tasks._ats_score(db_session, app) is None
