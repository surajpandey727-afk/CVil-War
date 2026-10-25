"""A dead file store must be reported, not hidden (D-018).

Production regression: the Supabase project behind ``STORAGE__PROVIDER=supabase`` was replaced,
but ``SUPABASE_URL`` still named the old one. Every upload parsed, then the storage write raised
``httpx.ConnectError`` and the request ended as a bare 500 with nothing in the log, while
``/health`` reported ``status: ok``. These tests pin the three halves of the fix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import func, select

from app.core.llm.discovery import Catalogue
from app.core.storage import keys
from app.core.storage.health import probe_storage
from app.core.storage.local import LocalFileStorage
from app.core.storage.supabase import SupabaseStorage
from app.models.resume import Resume
from tests.conftest import TEST_USER_ID

DOCX = (
    "resume.docx",
    b"PK\x03\x04 fake but correctly-signed docx bytes",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)


class _DeadStore:
    """Behaves like SupabaseStorage pointed at a project that no longer resolves."""

    async def put(self, key, data, *, content_type):  # noqa: ANN001, ANN201
        raise httpx.ConnectError("[Errno 16] Device or resource busy")

    async def get(self, key):  # noqa: ANN001, ANN201
        raise httpx.ConnectError("[Errno 16] Device or resource busy")

    async def materialize_to_temp(self, key, *, suffix=""):  # noqa: ANN001, ANN201
        raise httpx.ConnectError("[Errno 16] Device or resource busy")


class TestUploadWhenStorageIsDown:
    async def test_returns_503_with_a_readable_reason(self, client, db_session, tmp_path):
        import app.services.resume as resume_service

        with (
            patch.object(resume_service, "UPLOAD_DIR", tmp_path),
            patch.object(resume_service, "get_storage", return_value=_DeadStore()),
        ):
            resp = await client.post("/api/v1/resumes/upload", files={"file": DOCX})

        assert resp.status_code == 503
        body = resp.json()
        assert body["code"] == "STORAGE_UNAVAILABLE"
        assert "could not be saved" in body["detail"]

    async def test_writes_no_row_for_a_file_that_was_never_stored(
        self, client, db_session, tmp_path
    ):
        import app.services.resume as resume_service

        before = await db_session.scalar(
            select(func.count()).select_from(Resume).where(Resume.user_id == TEST_USER_ID)
        )
        with (
            patch.object(resume_service, "UPLOAD_DIR", tmp_path),
            patch.object(resume_service, "get_storage", return_value=_DeadStore()),
        ):
            await client.post("/api/v1/resumes/upload", files={"file": DOCX})
        after = await db_session.scalar(
            select(func.count()).select_from(Resume).where(Resume.user_id == TEST_USER_ID)
        )
        assert after == before

    async def test_cleans_up_the_parse_scratch_file(self, client, db_session, tmp_path):
        import app.services.resume as resume_service

        with (
            patch.object(resume_service, "UPLOAD_DIR", tmp_path),
            patch.object(resume_service, "get_storage", return_value=_DeadStore()),
        ):
            await client.post("/api/v1/resumes/upload", files={"file": DOCX})
        assert list(tmp_path.iterdir()) == []


class TestDownloadWhenStorageIsDown:
    async def _resume(self, db_session) -> Resume:
        r = Resume(
            user_id=TEST_USER_ID,
            name="cv",
            type="base",
            template_id="modern",
            file_path_docx=keys.upload_key(TEST_USER_ID, "abc", "docx"),
        )
        db_session.add(r)
        await db_session.commit()
        await db_session.refresh(r)
        return r

    async def test_an_unreachable_store_is_503_not_500(self, client, db_session):
        import app.api.v1.resumes as resumes_api

        r = await self._resume(db_session)
        with patch.object(resumes_api, "get_storage", return_value=_DeadStore()):
            resp = await client.get(f"/api/v1/resumes/{r.id}/download?format=docx")
        assert resp.status_code == 503
        assert resp.json()["code"] == "STORAGE_UNAVAILABLE"

    async def test_supabase_not_found_body_is_still_a_404(self, client, db_session):
        import app.api.v1.resumes as resumes_api

        request = httpx.Request("GET", "https://x.supabase.co/storage/v1/object/b/k")
        missing = httpx.Response(400, json={"statusCode": "404"}, request=request)

        class _Missing(_DeadStore):
            async def materialize_to_temp(self, key, *, suffix=""):  # noqa: ANN001, ANN201
                raise httpx.HTTPStatusError("400", request=request, response=missing)

        r = await self._resume(db_session)
        with patch.object(resumes_api, "get_storage", return_value=_Missing()):
            resp = await client.get(f"/api/v1/resumes/{r.id}/download?format=docx")
        assert resp.status_code == 404


class TestStorageProbe:
    async def test_local_root_that_is_writable_is_ok(self, tmp_path):
        result = await probe_storage(LocalFileStorage(str(tmp_path / "s"), "secret"))
        assert result == {"ok": True, "provider": "local", "error": None}

    async def test_supabase_missing_bucket_is_reported(self, monkeypatch):
        real = httpx.AsyncClient

        def _client(*a, **kw):  # noqa: ANN002, ANN003, ANN202
            return real(transport=httpx.MockTransport(lambda req: httpx.Response(404)))

        monkeypatch.setattr(httpx, "AsyncClient", _client)
        store = SupabaseStorage(base_url="https://p.supabase.co", service_key="k", bucket="b")
        result = await probe_storage(store)
        assert result["ok"] is False
        assert "404" in result["error"]

    async def test_supabase_unresolvable_host_is_reported_without_raising(self, monkeypatch):
        def _boom(req):  # noqa: ANN001, ANN202
            raise httpx.ConnectError("Name or service not known")

        real = httpx.AsyncClient
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda *a, **kw: real(transport=httpx.MockTransport(_boom))
        )
        store = SupabaseStorage(base_url="https://gone.supabase.co", service_key="k", bucket="b")
        result = await probe_storage(store)
        assert result == {"ok": False, "provider": "supabase", "error": "ConnectError"}

    async def test_health_reports_storage(self, client):
        fake = Catalogue(reachable=True, error=None, fetched_at=0.0)
        with patch("app.core.llm.discovery.discover", new=AsyncMock(return_value=fake)):
            body = (await client.get("/health")).json()
        assert set(body["storage"]) == {"ok", "provider", "error"}
