#!/usr/bin/env bash
# One-shot: fresh migration-owned schema + restore of real data into a new Supabase project.
#
#   DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:6543/postgres' \
#     bash scripts/setup_new_db.sh ../db_cluster-14-10-2026@06-46-25.backup
#
# Use the TRANSACTION POOLER string (port 6543), not db.<ref>.supabase.co:5432 — the direct host
# is IPv6-only and the serverless app is IPv4-only (docs/ARCHITECTURE_AUDIT.md §2). URL-encode any
# special characters in the password.
set -euo pipefail

BACKUP="${1:?Pass the backup file path as the first argument}"
: "${DATABASE_URL:?Set DATABASE_URL to the new project's transaction-pooler URL}"

HERE="$(cd "$(dirname "$0")/.." && pwd)"   # repo root (CVil War/)
PY="C:/Users/SurajPandey/.venvs/autoapply/Scripts/python.exe"

echo "==> 1/3  Creating the schema with Alembic (migration-owned, current head)"
( cd "$HERE/backend" && "$PY" -m alembic upgrade head )

echo "==> 2/3  Restoring real data from the backup"
"$PY" "$HERE/scripts/restore_from_backup.py" --backup "$BACKUP" --load

echo "==> 3/3  Verifying"
"$PY" - <<'PY'
import asyncio, os, asyncpg
async def main():
    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    c = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        ver = await c.fetchval("SELECT version_num FROM alembic_version")
        jobs = await c.fetchval("SELECT count(*) FROM jobs")
        resumes = await c.fetchval("SELECT count(*) FROM resumes")
        users = await c.fetchval("SELECT count(*) FROM users")
        print(f"alembic_version={ver}  users={users}  resumes={resumes}  jobs={jobs}")
    finally:
        await c.close()
asyncio.run(main())
PY
echo "Done. Point the cvil-war-api Vercel project's DATABASE_URL at this same URL and redeploy."
