# Test plan

What is tested, how, and where the evidence lives. Statuses use only PASS / FAIL / BLOCKED /
NOT RUN. Current results are in REGRESSION_RESULTS.md.

## 1. Smoke tests: production, every deploy

`cd backend; .venv\Scripts\python scripts\smoke_prod.py` (add `--base <url>` for another
environment, or `--skip-llm` to spend nothing). It uses a throwaway account, which it cleans up
at the end. It never approves or submits an application.

| ID | Journey | Pass criteria |
|---|---|---|
| S1 | API health | `/health` 200, `db: true`, `storage.ok: true`, LLM key reported present |
| S2 | SPA | `/login` served by the frontend project |
| S3 | Register + sign in | 201 then 200, bearer token issued |
| S4 | Résumé upload + download | 201; the downloaded DOCX matches what was uploaded |
| S5 | Jobs list | 200 under the UK-only policy |
| S6 | Résumé checker | 200; overall = Σ weight × score; matched skills carry verbatim quotes |
| S7 | Claude review | 200, `available: true`, every suggestion has an evidence status |
| S8 | Notifications feed | 200 with an unread count |
| S9 | Assistant + AI agents | roster 200; one chat turn returns a reply |
| S10 | Cleanup | résumé deleted, account soft-deleted |

Also on every deploy:
- `curl https://cvil-war-api.vercel.app/health`.
- The Keep-warm & uptime workflow, which retries cold starts and alerts on DB or storage loss.

## 2. Automated suites (CI on every push; run locally before every commit)

| Suite | Command | Scope |
|---|---|---|
| Backend lint | `ruff check app/` · `ruff format --check app/` | style, imports, ambiguity |
| Backend tests | `pytest -q` (Redis service + spaCy model in CI) | ~2,150 unit + integration tests on in-memory SQLite |
| Migrations | `tests/integration/test_migrations.py` | clean SQLite upgrade to head; Postgres when available |
| Frontend types | `tsc --noEmit` | strict TypeScript |
| Frontend lint | `eslint src --max-warnings=0` | |
| Frontend tests | `vitest run` | page, component and hook tests with MSW |
| Frontend build | `npm run build` | production bundle |
| Docker | CI `docker` job, `docker compose build` | backend + frontend images build |

## 3. Feature test inventory (this release)

| Area | Tests | What they prove |
|---|---|---|
| Upload/storage outage (D-018) | `test_storage_outage.py` (9) | dead store → 503 + no orphan row + scratch cleanup; download 404 vs 503; `/health` storage probe |
| LLM route (Claude) | `test_llm_anthropic.py` (15) | Sonnet default, Haiku for classification, explicit fallbacks; no temperature, JSON mode or gateway on Anthropic calls; missing key → skip/clear error; refusal falls through; invalid JSON rejected |
| DB-queue worker (D-016) | `test_db_queue_worker.py` (10) | claims approved/queued only, oldest first, all tenants; dry run writes nothing; hold back-off; API leaves work for the worker |
| Résumé checker | `test_resume_check_core.py` (19), `test_resume_check_api.py` (11), `ResumeCheckerPage.test.tsx` (10) | section parsing on wrapped PDF text; must vs nice classification; UK-only demand; the formula; the experience-policy guard (numbers, names, credentials, skills, placeholders → add-only-if-true); LLM output validation |
| Notifications | `test_notifications.py` (15), `NotificationBell.test.tsx` (6) | dedup, no caller rollback, email for the right kinds only, rehearsal ≠ submission, new jobs vs seen-again, best matches need a résumé, tenant isolation, badge/read/read-all |
| Assistant + agents | `test_assistant_*.py`, page tests | tool loop, confirmation tokens, tenant scope |

## 4. Manual / browser checks

| Check | How |
|---|---|
| Responsive layout 320–1920 px | local build against a scratch SQLite DB, same-origin iframes at 320/375/720/1100/1440/1920; measure `scrollWidth − clientWidth` |
| No design regression on existing pages | baseline (last release) vs current build: 12 pages × 3 widths, compare layout boxes |
| Gmail notifications | owner connects Gmail in Communications → "Send test email" → check the inbox |

## 5. Never tested against real employers

No real application is submitted by any test. Live apply (`BROWSER__LIVE_APPLY=true`) is the
owner's switch, used in review mode, with each application approved first.
