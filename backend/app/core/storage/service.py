"""Tenant-scoped storage facade: auto-prefixes keys and rejects cross-tenant access."""

from __future__ import annotations

from typing import Any

from app.core.storage.base import FileStorage, StoredObject
from app.core.storage.keys import user_prefix


class StorageService:
    """Confines a user to their ``users/{uid}/`` prefix (defense-in-depth, anti-IDOR)."""

    def __init__(self, storage: FileStorage, user_id: str) -> None:
        self._storage = storage
        self._prefix = user_prefix(user_id)

    def _check(self, key: str) -> str:
        if key != self._prefix and not key.startswith(self._prefix + "/"):
            raise PermissionError(f"key {key!r} is outside tenant prefix {self._prefix!r}")
        return key

    async def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        return await self._storage.put(self._check(key), data, content_type=content_type)

    async def get(self, key: str) -> bytes:
        return await self._storage.get(self._check(key))

    async def delete(self, key: str) -> None:
        await self._storage.delete(self._check(key))

    async def delete_prefix(self, prefix: str) -> int:
        """Delete everything under a tenant-confined prefix (e.g. the whole user tree)."""
        return await self._storage.delete_prefix(self._check(prefix))

    async def url_for(self, key: str, **kwargs: Any) -> str:
        return await self._storage.url_for(self._check(key), **kwargs)

    async def materialize_to_temp(self, key: str, *, suffix: str = "") -> str:
        return await self._storage.materialize_to_temp(self._check(key), suffix=suffix)
