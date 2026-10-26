"""Restore CVil-War's real data from a pg_dumpall cluster backup into a fresh Supabase project.

The schema is created by Alembic (``alembic upgrade head``), not by this script — the schema is
migration-owned, which is the whole point of "do it better this time": the structure is
reproducible from code, and only the *data* is carried across from the backup.

Usage (two steps, so the schema is in place before data loads):

    export DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<pw>@aws-1-<region>.pooler.supabase.com:6543/postgres'
    alembic upgrade head                      # from backend/, creates the current schema
    python ../scripts/restore_from_backup.py --backup <file> --load      # still from backend/

    python ../scripts/restore_from_backup.py --backup <file> --parse-only   # dry run, no DB

It loads tables in foreign-key-dependency order and loads self-referential tables (résumés
reference a base résumé) parent-rows-first, so a plain ordered COPY satisfies every constraint
without needing superuser trigger-disable rights the Supabase pooler role does not have.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys

# Parent tables before child tables. Within a table, rows are loaded in dump order except where
# noted. Any app table not listed is skipped (Supabase-managed schemas, roles, extensions, and
# alembic_version — the fresh migration sets its own version).
# Deliberately NOT restored: refresh_tokens and password_reset_tokens. They are ephemeral auth
# artifacts from a deployment that has been down for weeks — every one is stale, no session is
# live, and the owner simply logs in fresh. Restoring 263 dead sessions would be clutter at best.
LOAD_ORDER: list[str] = [
    "users",
    "user_settings", "user_llm_configs", "user_credentials", "platform_sessions",
    "jobs",
    "resumes",                       # self-ref base_resume_id — handled below
    "resume_branches", "resume_versions", "resume_changes", "job_resume_analyses",
    "documents", "document_versions",
    "applications",
    "application_events", "fit_analyses", "communication_events",
    "agent_runs", "run_trajectories", "run_verdicts", "run_diagnoses",
    "llm_usage",
    "domain_skills", "skill_feedback", "system_issues",
]

#: Tables with a self-referential FK: rows whose referenced column is NULL must load first.
SELF_REF: dict[str, str] = {"resumes": "base_resume_id"}


class Block:
    __slots__ = ("table", "columns", "rows")

    def __init__(self, table: str, columns: list[str], rows: list[str]):
        self.table = table
        self.columns = columns
        self.rows = rows


def parse_backup(path: str) -> dict[str, Block]:
    """Pull every ``COPY public.<table> (cols) FROM stdin;`` … ``\\.`` block from the dump."""
    blocks: dict[str, Block] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = iter(fh)
        for line in lines:
            if not line.startswith("COPY public."):
                continue
            # COPY public.jobs (id, user_id, ...) FROM stdin;
            header = line.strip()
            table = header.split("COPY public.", 1)[1].split(" ", 1)[0].strip('"')
            cols_part = header[header.index("(") + 1 : header.index(")")]
            columns = [c.strip().strip('"') for c in cols_part.split(",")]
            rows: list[str] = []
            for data in lines:
                if data.rstrip("\n") == "\\.":
                    break
                rows.append(data.rstrip("\n"))
            blocks[table] = Block(table, columns, rows)
    return blocks


def _order_rows(block: Block) -> list[str]:
    """For a self-referential table, put rows whose self-FK is NULL (``\\N``) first."""
    col = SELF_REF.get(block.table)
    if not col or col not in block.columns:
        return block.rows
    idx = block.columns.index(col)
    null_first, rest = [], []
    for row in block.rows:
        fields = row.split("\t")
        (null_first if idx < len(fields) and fields[idx] == "\\N" else rest).append(row)
    return null_first + rest


async def load(backup: str, database_url: str) -> None:
    import asyncpg

    # asyncpg wants a bare DSN, not SQLAlchemy's +asyncpg dialect prefix.
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
    blocks = parse_backup(backup)
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        loaded: list[tuple[str, int]] = []
        for table in LOAD_ORDER:
            block = blocks.get(table)
            if block is None or not block.rows:
                continue
            data = "\n".join(_order_rows(block)) + "\n"
            # pg_dump COPY is TEXT format (tab-delimited, \N = NULL) — asyncpg's default.
            await conn.copy_to_table(
                table, source=io.BytesIO(data.encode("utf-8")), columns=block.columns,
            )
            n = await conn.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608 (fixed names)
            loaded.append((table, n))
            print(f"  loaded {table:24s} {n} rows")
        print(f"\nDone. {sum(n for _, n in loaded)} rows across {len(loaded)} tables.")
        ok = await conn.fetchval("SELECT 1")
        print(f"SELECT 1 -> {ok}  (connection healthy)")
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", required=True)
    ap.add_argument("--load", action="store_true", help="load into $DATABASE_URL")
    ap.add_argument("--parse-only", action="store_true", help="parse and report, no DB")
    args = ap.parse_args()

    blocks = parse_backup(args.backup)
    present = [(t, len(blocks[t].rows)) for t in LOAD_ORDER if t in blocks and blocks[t].rows]
    print(f"Parsed {len(blocks)} COPY blocks; {len(present)} app tables carry data:")
    for t, n in present:
        print(f"  {t:24s} {n} rows")

    if args.parse_only:
        return
    if args.load:
        url = os.environ.get("DATABASE_URL")
        if not url:
            sys.exit("DATABASE_URL is not set — export the new project's pooler URL first.")
        asyncio.run(load(args.backup, url))


if __name__ == "__main__":
    main()
