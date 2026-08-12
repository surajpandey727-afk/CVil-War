"""Local-filesystem FileStorage implementation (development / self-hosted)."""

from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
import time
from pathlib import Path

import aiofiles

from app.core.storage.base import StoredObject


def _extended(path: Path) -> Path:
    """Opt a Windows path out of the 260-character ``MAX_PATH`` limit.

    Storage keys are inherently long — ``users/<32-char id>/uploads/<32-char>.pdf`` is ~60
    characters before the root. Add a checkout that is itself deeply nested (a synced
    "OneDrive - Some Long Company Name" folder is the common case) and writes fail with a bare
    ``FileNotFoundError`` from inside the thread-pool executor, which reads like a missing
    directory rather than a path-length problem.

    Prefixing an absolute path with ``\\\\?\\`` tells the Win32 API to skip ``MAX_PATH``
    normalisation, raising the limit to ~32,767 characters. The prefix demands a fully
    qualified path with backslash separators and no ``.``/``..`` components, which is why this
    is applied only after ``resolve()`` — and only to the value handed to the filesystem, never
    to the traversal check or to any key stored in the database.

    No-op off Windows, where no such limit exists.
    """
    if os.name != "nt":
        return path
    text = os.path.abspath(str(path))
    if text.startswith("\\\\?\\"):
        return path
    if text.startswith("\\\\"):  # UNC share: \\server\share -> \\?\UNC\server\share
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


class LocalFileStorage:
    """Stores objects under a local root. ``url_for`` returns a signed local route path."""

    def __init__(self, root: str, signing_secret: str) -> None:
        self._root = Path(root)
        self._signing_secret = signing_secret.encode()

    def _path(self, key: str) -> Path:
        resolved = (self._root / key).resolve()
        root = self._root.resolve()
        if not str(resolved).startswith(str(root)):
            raise ValueError(f"path traversal rejected for key: {key}")
        return _extended(resolved)

    async def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as fh:
            await fh.write(data)
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        async with aiofiles.open(self._path(key), "rb") as fh:
            return await fh.read()

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    async def delete_prefix(self, prefix: str) -> int:
        base = self._path(prefix)
        if not base.exists():
            return 0
        count = 0
        for path in base.rglob("*"):
            if path.is_file():
                path.unlink()
                count += 1
        return count

    async def url_for(
        self, key: str, *, expires_in: int = 300, download_name: str | None = None
    ) -> str:
        _ = download_name  # served by the files route (Phase 1/2); accepted for parity
        expiry = int(time.time()) + expires_in
        signature = self._sign(key, expiry)
        return f"/api/v1/files/{key}?expires={expiry}&sig={signature}"

    async def materialize_to_temp(self, key: str, *, suffix: str = "") -> str:
        data = await self.get(key)
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return tmp_path

    def _sign(self, key: str, expiry: int) -> str:
        message = f"{key}:{expiry}".encode()
        return hmac.new(self._signing_secret, message, hashlib.sha256).hexdigest()
