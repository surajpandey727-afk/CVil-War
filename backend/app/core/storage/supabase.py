"""Supabase Storage backend — the same Supabase project as ``database_url``, over its own
REST Storage API rather than the S3-compatible one.

Selected via ``STORAGE__PROVIDER=supabase``. Exists because the serverless deployment's
``local`` storage writes to ``/tmp``, which Vercel documents as ephemeral and instance-local —
correct for the parsing scratch space (see ``services.resume.UPLOAD_DIR``), wrong for a résumé
the operator expects to still be there tomorrow. Supabase Storage was already provisioned
alongside the Postgres database, so this reuses the project's existing service-role key
(``SUPABASE_SECRET_KEY``) rather than asking for a second, S3-specific access-key pair the
``S3FileStorage`` backend would need.

``httpx`` only — Supabase's Storage API is plain REST, no SDK dependency required.
"""

from __future__ import annotations

import os
import tempfile
from urllib.parse import quote

import httpx
import structlog

from app.core.storage.base import StoredObject

logger = structlog.get_logger(__name__)

_TIMEOUT = 20.0


class SupabaseStorage:
    """Async Supabase Storage blob store (bucket must already exist — see
    ``scripts/ensure_supabase_bucket.py``, run once at setup, not on every boot)."""

    def __init__(self, *, base_url: str, service_key: str, bucket: str) -> None:
        if not base_url or not service_key:
            raise ValueError(
                "Supabase storage selected (STORAGE__PROVIDER=supabase) but SUPABASE_URL / "
                "SUPABASE_SECRET_KEY are not set."
            )
        self._api = f"{base_url.rstrip('/')}/storage/v1"
        self._bucket = bucket
        self._headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    @staticmethod
    def _is_not_found(resp: httpx.Response) -> bool:
        """Supabase Storage wraps its real status in the JSON body rather than always using it
        as the transport status: a missing object answers with HTTP 400 and
        ``{"statusCode": "404", ...}``, not a plain 404 — verified live against the real API,
        not assumed from docs. ``resp.json()`` can itself fail (a non-JSON 400, a genuine
        gateway error), which must surface as the real error, not get swallowed as "not found"."""
        if resp.status_code == 404:
            return True
        if resp.status_code != 400:
            return False
        try:
            return resp.json().get("statusCode") == "404"
        except ValueError:
            return False

    def _object_url(self, key: str) -> str:
        # Every path segment quoted individually — a raw quote() would also escape the "/"
        # separators the key relies on to address a nested object.
        safe_key = "/".join(quote(part, safe="") for part in key.split("/"))
        return f"{self._api}/object/{self._bucket}/{safe_key}"

    async def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                self._object_url(key),
                content=data,
                headers={
                    **self._headers,
                    "Content-Type": content_type,
                    "x-upsert": "true",  # overwrite on key reuse rather than erroring
                },
            )
            resp.raise_for_status()
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(self._object_url(key), headers=self._headers)
            resp.raise_for_status()
            return resp.content

    async def exists(self, key: str) -> bool:
        # Not HEAD: verified live against the real API — a missing object answers HEAD with a
        # bare 400 and no body at all (no way to tell "not found" from a real error), while
        # GET at least wraps the true status in the JSON body (`{"statusCode": "404", ...}`).
        # The list endpoint sidesteps the inconsistency entirely by returning a plain array,
        # present-or-absent, which is what delete_prefix already relies on below.
        folder, _, name = key.rpartition("/")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{self._api}/object/list/{self._bucket}",
                headers=self._headers,
                json={"prefix": folder, "search": name, "limit": 1},
            )
            resp.raise_for_status()
            return any(entry.get("name") == name for entry in resp.json())

    async def delete(self, key: str) -> None:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.delete(self._object_url(key), headers=self._headers)
            # A delete of an already-absent key is not an error for any other backend here.
            if resp.status_code not in (200, 204) and not self._is_not_found(resp):
                resp.raise_for_status()

    async def delete_prefix(self, prefix: str) -> int:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            list_resp = await client.post(
                f"{self._api}/object/list/{self._bucket}",
                headers=self._headers,
                json={"prefix": prefix, "limit": 1000},
            )
            list_resp.raise_for_status()
            entries = list_resp.json()
            if not entries:
                return 0
            keys = [f"{prefix.rstrip('/')}/{e['name']}" for e in entries if e.get("name")]
            if not keys:
                return 0
            del_resp = await client.request(
                "DELETE",
                f"{self._api}/object/{self._bucket}",
                headers=self._headers,
                json={"prefixes": keys},
            )
            del_resp.raise_for_status()
            return len(keys)

    async def url_for(
        self, key: str, *, expires_in: int = 300, download_name: str | None = None
    ) -> str:
        safe_key = "/".join(quote(part, safe="") for part in key.split("/"))
        body: dict[str, object] = {"expiresIn": expires_in}
        if download_name:
            body["download"] = download_name
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{self._api}/object/sign/{self._bucket}/{safe_key}",
                headers=self._headers,
                json=body,
            )
            resp.raise_for_status()
            signed_path = resp.json()["signedURL"]
        # The API returns a path (e.g. "/object/sign/<bucket>/<key>?token=...") relative to
        # /storage/v1, not a full URL.
        return f"{self._api}{signed_path}"

    async def materialize_to_temp(self, key: str, *, suffix: str = "") -> str:
        data = await self.get(key)
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return tmp_path
