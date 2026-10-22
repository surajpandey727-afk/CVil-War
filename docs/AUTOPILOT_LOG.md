# Autopilot session log — 2026-10-23

Owner away 3–6h; full autonomy granted. Acting as principal architect, cloud/data engineer and
senior UX designer. This log records every decision and why, so nothing needs re-explaining on
return. Commits are local only (not pushed) until the DB is back — see the note below.

## Standing constraints I am working around (not faking)
- **Prod DB restore is blocked on the owner.** Supabase masks the new project's password; I
  cannot read it. The restore toolkit is staged and parse-verified (prior commit). Production
  stays down until the owner runs `scripts/setup_new_db.sh` with the pooler URL.
- **Vercel env/CLI lost authorization** (audit §17). I cannot change prod config or redeploy.
- **Commits are local, not pushed.** Pushing would start `keepwarm.yml`, which would fail every
  10 min against the dead DB and email the owner while they are away. I push nothing; the owner
  pushes when the DB is live.
- All builds are verified locally against scratch SQLite + seeded data in the browser preview.

## Priorities (my call, highest value for "I've never been able to use it")
1. Skill Radar **frontend** — the feature the owner detailed; the "see it work" moment.
2. Notifications — real application-event email (SMTP, not Gmail-dependent) + a status panel so
   the owner can *see* what is configured and why an email did or didn't go.
3. UX funnel overhaul — the owner called the UX "shit"; make empty/degraded states instruct
   instead of dead-end, and make the core funnel (jobs → score → tailor → apply) cohesive.
4. Production hardening (code-only, no deploy): 5xx-as-outage on login, CSP, prod openapi off,
   route-level code-splitting.
5. Dynamic sources (Dreamwork-style free API boards).
6. Keep both suites green; finish with a summary.

## Progress
- [ ] 1. Skill Radar frontend
- [ ] 2. Notifications + status panel
- [ ] 3. UX funnel overhaul
- [ ] 4. Production hardening
- [ ] 5. Dynamic sources
- [ ] 6. Suites green + summary

(Entries appended below as each lands.)

---
### ✅ DB RESTORED (owner handed over the password mid-session)
- Owner provided the DB password and authorized Chrome use. His Supabase session had expired,
  so I did **not** log in (entering credentials to authenticate is a line I hold). Instead I
  discovered the pooler host by probing all Supabase regions with his credentials:
  **`aws-1-eu-west-3.pooler.supabase.com`** (Paris), project ref `dcpuwibweqsgtfknazhy`.
- `alembic upgrade head` FAILS on fresh Postgres — the historical migrations were only ever run
  on SQLite (enums degrade to VARCHAR there). `job_os_core` adds enum columns via batch
  add_column (no auto CREATE TYPE on PG) and uses unquoted enum/text server-defaults
  (`DEFAULT healthy` reads as a column reference). This is a latent bug: fresh-Postgres schema
  reproduction was never tested. Logged as a follow-up to fix properly.
- **Built the schema from the SQLAlchemy models instead** (`scripts/build_schema_from_models.py`):
  `Base.metadata.create_all` emits correct Postgres DDL (proper enum types, quoted defaults),
  then stamped `alembic_version` = head `a3d9c51e7b20`. 28 tables, 23 enum types.
- Restored real data (`scripts/restore_from_backup.py`): **2,423 rows** — user, settings,
  2,119 jobs, 5 résumés (his real CVs: MLOps, AIPM, AI Product Analyst), 39 applications,
  157 application events, 4 fit analyses, 82 agent runs, 15 LLM-usage rows.
- Verified via the app's OWN engine on the transaction pooler (6543, the mode Vercel uses):
  SELECT 1 OK, jobs 2119, resumes 5. Corpus is rich (357 python / 1,482 product / 551 ML
  jobs), so the Skill Radar's live enrichment will work.
- **No secret committed anywhere.** Scripts read the URL from the environment; the password
  lives only in the shell for the run.
- REMAINING for full prod: the live API's `DATABASE_URL` env on Vercel still points at the dead
  project. Must be set to the new 6543 pooler URL and redeployed. Attempting via Chrome next;
  if the Vercel session isn't live I leave it for the owner (I won't log in).
