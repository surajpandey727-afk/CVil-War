"""One-time setup: create the Supabase Storage bucket app.core.storage.supabase expects.

Run once per Supabase project (idempotent — a 409 "already exists" is treated as success),
not on every boot. Needs SUPABASE_URL and SUPABASE_SECRET_KEY in the environment or .env.

    python scripts/ensure_supabase_bucket.py [bucket-name]
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

import httpx

from app.config.settings import get_settings


async def main() -> None:
    bucket = sys.argv[1] if len(sys.argv) > 1 else "cvilwar-files"
    settings = get_settings()
    base = settings.supabase_url.rstrip("/")
    key = settings.supabase_secret_key.get_secret_value()
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SECRET_KEY not set.")

    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{base}/storage/v1/bucket",
            headers=headers,
            # Private bucket: every read goes through url_for's signed URL, never a public one.
            json={"name": bucket, "id": bucket, "public": False},
        )
        if resp.status_code == 200:
            print(f"created bucket {bucket!r}")
        elif resp.status_code == 400 and "already exists" in resp.text.lower():
            print(f"bucket {bucket!r} already exists — nothing to do")
        else:
            resp.raise_for_status()


asyncio.run(main())
