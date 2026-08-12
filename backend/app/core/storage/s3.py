"""S3-compatible object storage (AWS S3, Cloudflare R2, Backblaze B2, MinIO).

Selected via ``STORAGE__PROVIDER=s3``. ``aioboto3`` is imported lazily (it lives in the
``[aws]`` extra) so importing this module never requires the dependency. Keys are the same
opaque ``users/{uid}/…`` paths the local backend uses; ``StorageService`` enforces tenant
prefixes on top. ``url_for`` returns a presigned GET URL so clients can download directly
from the bucket (no egress through the app).
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import structlog

from app.core.storage.base import StoredObject

logger = structlog.get_logger(__name__)


class S3FileStorage:
    """Async S3 / S3-compatible blob store."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        import aioboto3  # type: ignore[import-untyped]  # lazy: only needed when provider=s3

        self._bucket = bucket
        self._session = aioboto3.Session()
        self._client_kwargs: dict[str, Any] = {"service_name": "s3"}
        if region:
            self._client_kwargs["region_name"] = region
        if endpoint_url:  # e.g. Cloudflare R2 / MinIO
            self._client_kwargs["endpoint_url"] = endpoint_url
        if access_key_id and secret_access_key:
            self._client_kwargs["aws_access_key_id"] = access_key_id
            self._client_kwargs["aws_secret_access_key"] = secret_access_key

    def _client(self) -> Any:
        """Return an async-context-manager S3 client."""
        return self._session.client(**self._client_kwargs)

    async def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        async with self._client() as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        async with self._client() as s3:
            resp = await s3.get_object(Bucket=self._bucket, Key=key)
            async with resp["Body"] as stream:
                return await stream.read()  # type: ignore[no-any-return]

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                # Only a genuine not-found is "absent"; real errors (403/500/throttle) propagate.
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise
            return True

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under ``prefix`` (D9 account purge). Returns the count actually
        deleted; raises if S3 reports per-object errors so a purge can't falsely report success."""
        deleted = 0
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                if not objects:
                    continue
                resp = await s3.delete_objects(Bucket=self._bucket, Delete={"Objects": objects})
                deleted += len(resp.get("Deleted", []))
                errors = resp.get("Errors", [])
                if errors:
                    logger.error("s3.delete_prefix_errors", prefix=prefix, errors=len(errors))
                    raise RuntimeError(f"delete_prefix: {len(errors)} object(s) failed")
        return deleted

    async def url_for(
        self, key: str, *, expires_in: int = 300, download_name: str | None = None
    ) -> str:
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        async with self._client() as s3:
            return await s3.generate_presigned_url(  # type: ignore[no-any-return]
                "get_object", Params=params, ExpiresIn=expires_in
            )

    async def materialize_to_temp(self, key: str, *, suffix: str = "") -> str:
        data = await self.get(key)
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return tmp_path
