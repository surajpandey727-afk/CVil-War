# Release assessment — 2026-10-25

## Verdict

**Shippable, and shipped.** Résumé upload is fixed in production. CI is green for the first time
(backend, frontend, Docker). The LLM runs on Claude via the Anthropic API, and the new
features are live and smoke-tested on production: the résumé checker, notifications with a
daily discovery run, the application pack, and the assistant with its AI Agents roster.

Two things remain the owner's to do; neither is a code gap:
1. Connect Gmail in Communications so email copies and the daily digest can go out.
2. Decide whether this machine should make real submissions: run the DB-queue worker with
   `BROWSER__LIVE_APPLY=true` and production's `SECRETS__APP_KEYS`.

## Release gates

| Gate | Status | Evidence / reason |
|---|---|---|
| Résumé upload works in production | PASS | Smoke S4: upload → download round trip on cvil-war.vercel.app; root cause and fix in D-018 |
| CI green (backend, frontend, docker) | PASS | GitHub Actions run 40160487508 on `71dd696`: all three jobs success |
| `docker compose up --build` from a clean checkout | see REGRESSION_RESULTS | clean clone of `main`, no `.env` |
| LLM is Claude, key only from `ANTHROPIC_API_KEY`, fallback kept | PASS | real calls (Sonnet 5.5, Haiku 5.5); prod `/health` reports `anthropic_key_configured: true`; fallback `anthropic/claude-haiku-5-5`; key never printed, logged or committed (secret scans 0 hits) |
| Every LLM JSON response validated before use | PASS | `complete_json` schema validation; checker review rejects unknown sections and non-verbatim originals; assistant tool inputs validated; tests in `test_llm_anthropic.py`, `test_resume_check_core.py`, `test_assistant_loop.py` |
| Experience policy (never invent; "add only if true") | PASS | one guard decides evidence status for rules, Claude and the application pack; 6 policy tests + API tests |
| UK-only jobs policy intact | PASS | `core/geo` untouched; its tests pass; demand counts and best matches use UK-eligible jobs only (US posting excluded in a test) |
| Production automation host (D-016) | PASS (mechanism) / BLOCKED (live submission, owner's decision) | DB-queue worker; prod dry run lists exactly the 2 waiting applications; `APPLY_DISPATCH=db_queue` in prod |
| No real application submitted | PASS | none submitted; all tests mock the browser; prod probes used throwaway accounts and never approved anything |
| Production DB changes additive, backed up, previewed, session pooler | PASS | JSON export of all 28 tables (2,470 rows) before the change; `alembic upgrade e5b2c8d41f07:head --sql` previewed (one `CREATE TABLE` + indexes); applied over :5432; row counts of existing tables unchanged |
| Responsive 320–1920 px, no design regression | PASS | 12 existing pages × 3 widths identical to the previous release apart from the new sidebar link; new pages 0 px overflow (REGRESSION_RESULTS) |
| Zero open P0 | PASS | D-018 fixed |
| Zero open P1 | PASS for code; BLOCKED items need the owner (Gmail OAuth, live-submit decision) | D-012 (P2) and D-017 (P3) remain open |

## Production changes made (all additive or config)

1. Supabase: private storage bucket `cvilwar-files` created in the live project.
2. Vercel `cvil-war-api` env: `SUPABASE_URL` and `SUPABASE_SECRET_KEY` repointed to the live
   project; `ANTHROPIC_API_KEY` added (sensitive); `LLM__DEFAULT_MODEL` set to
   `anthropic/claude-sonnet-5-5`, `LLM__PREFERRED_PROVIDER` to `anthropic`;
   `APPLY_DISPATCH=db_queue`; `CRON_SECRET` added (sensitive).
3. Alembic `e5b2c8d41f07 → f7c3a9e1d2b4`: new `notifications` table only.
4. Daily discovery ran twice to verify the cron path: 314 new jobs (304 UK-eligible) added to
   the owner's account; 9 strong-match and 3 new-jobs notifications.
5. Anthropic Console: API key `cvil-war-prod` in the SimplyPhi org's Default workspace (the
   workspace the owner named), expiring 2027-10-24. **Its usage bills to SimplyPhi.**
6. Throwaway QA accounts (`qa-*@example.com`) were created by the smoke tests and
   soft-deleted.

## Not done (carried forward)

- D-012 batch description enrichment; D-017 sidebar auto-expand.
- The assistant has no persistent conversation memory. Each chat sends its history from the
  browser session.
- The Assistant and Résumé agents have no run log (needs an `AgentName` enum migration).
- Phase 4 LatticeLoader decision (from the previous assessment) is still the owner's call.
