"""SupabaseStorage — the résumé-durability fix. Local/serverless storage wrote to /tmp,
which Vercel documents as ephemeral and instance-local; this backend persists to the same
Supabase project the database already lives in, over its native REST Storage API (no
separate S3 access-key pair to provision, unlike S3FileStorage).

httpx.MockTransport rather than a real server (no Supabase-Storage-compatible moto
equivalent exists) — asserts the exact request shape (method, URL, headers, body) each
operation sends, and returns a canned response matching Supabase's real API shape.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.storage.supabase import SupabaseStorage

_BASE = "https://proj.supabase.co"
_KEY = "service-role-secret"
_BUCKET = "cvilwar-files"


class TestSupabaseStorageInit:
    def test_requires_base_url_and_key(self):
        with pytest.raises(ValueError, match="STORAGE__PROVIDER=supabase"):
            SupabaseStorage(base_url="", service_key="", bucket=_BUCKET)

    def test_api_root_and_headers(self):
        store = SupabaseStorage(base_url=_BASE + "/", service_key=_KEY, bucket=_BUCKET)
        assert store._api == f"{_BASE}/storage/v1"
        assert store._headers["Authorization"] == f"Bearer {_KEY}"
        assert store._headers["apikey"] == _KEY


_RealAsyncClient = httpx.AsyncClient  # captured before any test monkeypatches the name


def _mock_client(handler):
    """Build an AsyncClient wired to a MockTransport, then monkeypatch httpx.AsyncClient
    (module-global, used as a context manager inside every SupabaseStorage method) to return
    it for the duration of one `async with` block."""

    class _CtxClient:
        def __init__(self, *a, **kw):
            self._real = _RealAsyncClient(transport=httpx.MockTransport(handler))

        async def __aenter__(self):
            return self._real

        async def __aexit__(self, *exc):
            await self._real.aclose()

    return _CtxClient


class TestPut:
    async def test_put_posts_bytes_with_upsert(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["url"] = str(request.url)
            seen["headers"] = dict(request.headers)
            seen["body"] = request.content
            return httpx.Response(200, json={"Key": f"{_BUCKET}/users/u1/r.pdf"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)

        meta = await store.put("users/u1/r.pdf", b"%PDF-1.4 fake", content_type="application/pdf")

        assert seen["method"] == "POST"
        assert seen["url"] == f"{_BASE}/storage/v1/object/{_BUCKET}/users/u1/r.pdf"
        assert seen["headers"]["x-upsert"] == "true"
        assert seen["headers"]["content-type"] == "application/pdf"
        assert seen["headers"]["authorization"] == f"Bearer {_KEY}"
        assert seen["body"] == b"%PDF-1.4 fake"
        assert meta.key == "users/u1/r.pdf"
        assert meta.size == len(b"%PDF-1.4 fake")

    async def test_put_encodes_each_path_segment(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)

        await store.put("users/u1/my résumé.pdf", b"x", content_type="application/pdf")

        # The "/" separators survive encoding; the space inside a segment does not.
        assert seen["url"] == f"{_BASE}/storage/v1/object/{_BUCKET}/users/u1/my%20r%C3%A9sum%C3%A9.pdf"

    async def test_put_raises_on_http_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "denied"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)

        with pytest.raises(httpx.HTTPStatusError):
            await store.put("users/u1/r.pdf", b"x", content_type="application/pdf")


class TestGet:
    async def test_get_returns_raw_bytes(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            return httpx.Response(200, content=b"the actual file bytes")

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)

        assert await store.get("users/u1/r.pdf") == b"the actual file bytes"


class TestExists:
    """Not HEAD -- verified live against the real Supabase project: HEAD on a missing object
    answers with a bare 400 and no body, so there is no way to tell "not found" from a real
    error. exists() goes through the list endpoint instead, same as delete_prefix."""

    async def test_exists_true_when_the_name_is_in_the_listing(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=[{"name": "r.pdf"}])

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)

        assert await store.exists("users/u1/r.pdf") is True
        assert seen["url"] == f"{_BASE}/storage/v1/object/list/{_BUCKET}"
        assert seen["body"] == {"prefix": "users/u1", "search": "r.pdf", "limit": 1}

    async def test_exists_false_on_an_empty_listing(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "AsyncClient", _mock_client(lambda r: httpx.Response(200, json=[]))
        )
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)
        assert await store.exists("users/u1/missing.pdf") is False

    async def test_exists_raises_on_real_error(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "AsyncClient", _mock_client(lambda r: httpx.Response(500))
        )
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)
        with pytest.raises(httpx.HTTPStatusError):
            await store.exists("users/u1/r.pdf")


class TestDelete:
    async def test_delete_absent_key_is_not_an_error(self, monkeypatch):
        """The literal shape the real API returns for a missing key -- 400 transport status
        with the true 404 wrapped in the body. A bare ``status_code in (200, 204, 404)`` check
        (the first version of this) never catches this case and raises on every delete of an
        already-gone key, which is routine (a double-click, a retry)."""
        monkeypatch.setattr(
            httpx, "AsyncClient",
            _mock_client(lambda r: httpx.Response(
                400, json={"statusCode": "404", "error": "not_found", "message": "Object not found"}
            )),
        )
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)
        await store.delete("users/u1/already-gone.pdf")  # must not raise

    async def test_delete_a_plain_404_is_also_not_an_error(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "AsyncClient", _mock_client(lambda r: httpx.Response(404))
        )
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)
        await store.delete("users/u1/already-gone.pdf")  # must not raise

    async def test_delete_real_error_raises(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "AsyncClient", _mock_client(lambda r: httpx.Response(500))
        )
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)
        with pytest.raises(httpx.HTTPStatusError):
            await store.delete("users/u1/r.pdf")

    async def test_delete_a_400_that_is_not_actually_a_404_still_raises(self, monkeypatch):
        """A 400 body without the 404 wrapper shape is a real error (bad request, malformed
        key, ...) and must not be silently swallowed by the not-found tolerance above."""
        monkeypatch.setattr(
            httpx, "AsyncClient",
            _mock_client(lambda r: httpx.Response(400, json={"error": "invalid_key"})),
        )
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)
        with pytest.raises(httpx.HTTPStatusError):
            await store.delete("users/u1/r.pdf")


class TestDeletePrefix:
    async def test_lists_then_bulk_deletes(self, monkeypatch):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, str(request.url), request.content))
            if request.url.path.endswith("/object/list/" + _BUCKET):
                return httpx.Response(200, json=[{"name": "a.pdf"}, {"name": "b.pdf"}])
            return httpx.Response(200, json={"message": "deleted"})

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)

        count = await store.delete_prefix("users/u1")

        assert count == 2
        list_call = calls[0]
        assert list_call[0] == "POST"
        assert json.loads(list_call[2])["prefix"] == "users/u1"
        delete_call = calls[1]
        assert delete_call[0] == "DELETE"
        assert set(json.loads(delete_call[2])["prefixes"]) == {"users/u1/a.pdf", "users/u1/b.pdf"}

    async def test_empty_prefix_deletes_nothing(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "AsyncClient", _mock_client(lambda r: httpx.Response(200, json=[]))
        )
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)
        assert await store.delete_prefix("users/empty") == 0


class TestUrlFor:
    async def test_returns_a_full_url_from_the_relative_signed_path(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200, json={"signedURL": f"/object/sign/{_BUCKET}/users/u1/r.pdf?token=abc"}
            )

        monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)

        url = await store.url_for("users/u1/r.pdf", expires_in=120, download_name="My CV.pdf")

        assert seen["url"] == f"{_BASE}/storage/v1/object/sign/{_BUCKET}/users/u1/r.pdf"
        assert seen["body"] == {"expiresIn": 120, "download": "My CV.pdf"}
        assert url == f"{_BASE}/storage/v1/object/sign/{_BUCKET}/users/u1/r.pdf?token=abc"


class TestMaterializeToTemp:
    async def test_writes_bytes_to_a_real_temp_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            httpx, "AsyncClient", _mock_client(lambda r: httpx.Response(200, content=b"DATA"))
        )
        store = SupabaseStorage(base_url=_BASE, service_key=_KEY, bucket=_BUCKET)

        path = await store.materialize_to_temp("users/u1/r.pdf", suffix=".pdf")

        assert path.endswith(".pdf")
        with open(path, "rb") as fh:
            assert fh.read() == b"DATA"
