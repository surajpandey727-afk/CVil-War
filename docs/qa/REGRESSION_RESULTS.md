# Regression results — 2026-10-25

Statuses: PASS / FAIL / BLOCKED / NOT RUN.

## Automated

| Suite | Command | Result | Status |
|---|---|---|---|
| Backend tests (local) | `pytest -q` | 2,185 passed, 2 skipped, 1 xfailed, 0 failed | PASS |
| Backend tests (clean Linux, as CI) | python:3.12 container, `pip install -c constraints.txt -e .[dev]`, spaCy model, Redis | 2,176 passed; the remaining 7 traced to a real tailoring bug (fixed, see D-028; its regression test fails on the old code) and to `docs/` not being copied into the container | PASS after fixes |
| Backend lint | `ruff check app/` · `ruff format --check app/` | clean · 308 files formatted | PASS |
| Frontend types | `tsc --noEmit` | clean | PASS |
| Frontend lint | `eslint src --max-warnings=0` | clean | PASS |
| Frontend tests | `vitest run` | 59 files, 482 passed | PASS |
| Frontend build | `npm run build` | built (pre-existing >500 kB chunk warning) | PASS |
| GitHub CI | backend · frontend · docker | run 40160487508 (`71dd696`): all three success, the first fully green run | PASS |
| `pip install` from clean (D-013) | clean python:3.12 container | 85 s, `pip check` clean | PASS |
| `docker compose up --build`, clean clone of `main`, no `.env` | `REDIS_HOST_PORT=6391` (6379 taken by another local project) | backend, worker, frontend, redis **healthy**; migrate exited 0; `/health` db/redis/storage ok; frontend 200; `/api` proxied (401 unauthenticated); spaCy loads in the worker | PASS |

## Production (https://cvil-war.vercel.app)

| Check | Result | Status |
|---|---|---|
| Smoke S1–S10 (`scripts/smoke_prod.py`) | 10/10: health, SPA, register, upload + download, jobs, checker, Claude review (Sonnet 5.5, 14 s, 0 rejected), notifications, assistant + agents, cleanup | PASS |
| Real Claude calls through the app client | Sonnet 5.5 1.4 s / $0.0006; Haiku 5.5 1.4 s / $0.00003; JSON validated | PASS |
| `/health` | db true, storage supabase ok, `anthropic_key_configured: true`, default `anthropic/claude-sonnet-5-5` | PASS |
| Daily cron (`/internal/cron/daily`) | 401 without the secret; with it: discovery done (446 found), inbox sync ok, digest 0 (Gmail not connected), 92 s | PASS |
| Notifications produced by the real run | 304 new UK jobs; 9 strong-match + 3 new-jobs notifications for the owner | PASS |
| Gmail email copy / digest | needs the owner to connect Gmail (OAuth consent) | BLOCKED |
| DB-queue worker vs prod (dry run, session pooler :5432) | lists exactly the 2 waiting applications; writes nothing | PASS |
| Live submission from the worker | owner's decision + `SECRETS__APP_KEYS`; never run in this session by policy | NOT RUN |
| Migration `e5b2c8d41f07 → f7c3a9e1d2b4` | JSON backup (28 tables, 2,470 rows) → `--sql` preview → applied; existing row counts unchanged | PASS |

## Browser (local build, scratch SQLite DB — never production)

| Check | Result | Status |
|---|---|---|
| Existing pages unchanged | 12 pages × 375/1100/1536: layout identical to the previous release; only difference is the new sidebar link | PASS |
| New/changed pages, 320–1920 px | Assistant, AI Agents, application page with pack open, dashboard with the bell open, Résumé checker: 0 px horizontal overflow at 320/375/720/1100/1440/1920 | PASS |
| Notification panel at 320/375 px | was clipped off-screen (anchored to the bell); now pinned to the viewport with a 12 px gutter; verified inside at 320/375/720/1440 | PASS (fixed) |
| Assistant with real Claude | used 3 read tools, reported honestly, declined to stage when nothing qualified; markdown now rendered (was raw `**`) | PASS (fixed) |

## 2026-10-26 — Applications dead ends and the codebase-wide sweep (D-037 to D-063)

| Suite | Result | Status |
|---|---|---|
| Backend `pytest -q` | 2,248 passed, 2 skipped, 1 xfailed, 0 failed | PASS |
| Backend lint | `ruff check app/` · `ruff format --check app/` clean | PASS |
| Frontend | `tsc` clean · `eslint --max-warnings=0` clean · `vitest` 61 files, 500 passed · build OK | PASS |
| Old-code check | the approval-loop tests (3) and the dashboard/notification/state tests fail on the previous code | PASS |
| Browser, scratch DB (never production) | Applications at 1440 / 375 / 320 px: each row shows its real blocker (approval, LinkedIn sign-in, automation host, run-window hold, paused at a check); 0 px overflow after fixes to the next-step buttons, the tab row and the bulk-tailor select | PASS |
| Caught in the browser, fixed | career-page rows said "needs your Monzo sign-in": the platform list carries an unavailable "connect" action for keyless sources, and the helper ignored `available` | PASS (test added) |
| Production deploy | not done from this machine: its Vercel CLI is signed in to another account and the deploy token is not available here | NOT RUN |
| Live submission | never run by policy; mechanism tested with the browser mocked | NOT RUN |
