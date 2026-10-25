"""Readiness probe for the configured file store, reported by ``/health``.

Exists because a dead storage backend was invisible: ``/health`` said ``status: ok`` while
every résumé upload failed, since the Supabase project URL in production still pointed at a
project that no longer existed. The probe answers one question cheaply — can this process reach
the bucket it would write to — without writing anything.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from app.core.storage.local import LocalFileStorage
from app.core.storage.supabase import SupabaseStorage

PROBE_TIMEOUT_S = 3.0
_PROVIDER_NAMES: dict[type, str] = {SupabaseStorage: "supabase", LocalFileStorage: "local"}


async def probe_storage(storage: object) -> dict[str, object]:
    """Return ``{"ok": bool, "provider": str, "error": str | None}`` for ``storage``.

    Never raises: a readiness probe that throws turns one broken dependency into a broken
    health endpoint.
    """
    provider = _PROVIDER_NAMES.get(type(storage), type(storage).__name__)
    try:
        if isinstance(storage, SupabaseStorage):
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
                resp = await client.get(
                    f"{storage._api}/bucket/{storage._bucket}", headers=storage._headers
                )
            if resp.status_code == 200:
                return {"ok": True, "provider": "supabase", "error": None}
            return {
                "ok": False,
                "provider": "supabase",
                "error": f"bucket check returned HTTP {resp.status_code}",
            }
        if isinstance(storage, LocalFileStorage):
            root = Path(storage._root)
            root.mkdir(parents=True, exist_ok=True)
            ok = os.access(root, os.W_OK)
            return {
                "ok": ok,
                "provider": "local",
                "error": None if ok else "storage root is not writable",
            }
        # S3 and anything else: configured, not probed (no cheap unauthenticated check).
        return {"ok": True, "provider": provider, "error": None}
    except Exception as exc:  # deliberately broad — see docstring
        return {"ok": False, "provider": provider, "error": type(exc).__name__}
