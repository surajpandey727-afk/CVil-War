# Defect register

Severity: **P0** data loss / security / false submission · **P1** core promise broken ·
**P2** significant degradation · **P3** polish.
Status (only these four): **PASS** fixed and verified · **FAIL** open · **BLOCKED** cannot
proceed without something outside the code · **NOT RUN** not yet verified.

| ID | Sev | Area | Defect | Root cause | Status | Verification |
|---|---|---|---|---|---|---|
| D-001 | P1 | Discovery | 48% of listed jobs were outside the UK | No country field; global boards stored unfiltered | PASS | 1,039 prod rows `uk_eligible=false`; list filters in SQL; 89 classifier tests |
| D-002 | P1 | Discovery | No posting date on any job | `_listing_to_job` dropped `posted_at` | PASS (new/re-discovered jobs) | `test_job_service.py`. Existing rows are not back-dated: that would be fabrication |
| D-003 | P1 | Jobs UI | City/country not shown; raw postcodes shown | No normalised location | PASS | `JobSearchPage.location.test.tsx` |
| D-004 | P1 | Jobs UI | Results squeezed into a sliver | Flex `min-width:auto` | PASS | Measured 320–1920 px, 0 px overflow |
| D-005 | P1 | Jobs UI | "Searching…" never finished | Client timeout shorter than server time | PASS | Live search 23.5 s |
| D-006 | P2 | Jobs UI | Only the first 100 jobs reachable | A single page was fetched | PASS | Pager test |
| D-007 | P2 | Data | Header count didn't match listable jobs | Counted every row | PASS | `test_dashboard_job_counts_are_uk_eligible_only` |
| D-008 | P2 | Discovery | Linked duplicates listed separately | Ignored `canonical_job_id` | PASS | `TestDuplicatesCollapse` |
| D-009 | P2 | Shell | Sidebar left 18 px of page at 320 px | Sidebar never collapsed | PASS | Measured |
| D-010 | P2 | Jobs UI | "Scoring matches…" stuck | One boolean shared by overlapping batches | PASS | In-flight counter |
| D-011 | P3 | Filters | Dublin offered as a city | Legacy table | PASS | Removed |
| D-012 | P2 | Discovery | 302 jobs without a description | LinkedIn guest cards carry none | FAIL | Enrichment on drawer open works; batch enrichment not built |
| D-013 | P2 | CI | Backend `pip install` fails with `resolution-too-deep` | Unused, unbounded `langchain-*` packages and an open `browser-use` range, against browser-use's exact pins | PASS | `constraints.txt` (uv-compiled). Clean python:3.12 container: install 85 s, `pip check` clean. CI install step green |
| D-014 | P2 | CI / Docker | Backend image build fails | resolution-too-deep (D-013); the base image's pip 25.0.1 crashes on constraint markers; the CI gha cache had no buildx builder | PASS | CI `docker` job green (run 40150616596) |
| D-015 | P2 | Data | Dashboard said "3 Applied", pipeline "0" | Pipeline counted only the 20 most recent | PASS | `DashboardPage.test.tsx` |
| D-016 | P1 | Automation | Apply pipeline cannot run in production | No worker or browser on Vercel | PASS (mechanism) · BLOCKED (live submissions) | DB-queue worker, 10 tests. A prod dry run over the session pooler lists exactly the 2 waiting applications. `APPLY_DISPATCH=db_queue` is set in prod. Live submission needs the owner's `SECRETS__APP_KEYS` on the worker machine and their own decision to set `BROWSER__LIVE_APPLY=true` (LOCAL_SETUP.md) |
| D-017 | P3 | Shell | Auto-collapsed sidebar stays collapsed after widening | Collapse persisted, never auto-expanded | FAIL | The header toggle restores it |
| D-018 | P0 | Uploads | **Résumé upload failed in production** (500) | `STORAGE__PROVIDER=supabase` still pointed at the deleted Supabase project; the new project had no bucket; the failure wasn't logged | PASS | Bucket created and env repointed; prod upload→download byte-identical. The code now returns 503 `STORAGE_UNAVAILABLE` with a log line and no orphan row; `/health` reports storage. 9 tests, 6 of which fail on the old code |
| D-019 | P2 | Ops | Keep-warm "failed" repeatedly while prod was healthy | A single 25 s attempt vs a cold start of about 28 s for the 280 MB function (smoke S1 measured 28.0 s) | PASS | 3 attempts × 50 s with status and timing logged; also alerts on storage loss |
| D-020 | P1 | LLM | Production LLM pointed at a local OmniRoute gateway Vercel can't reach | Earlier configuration | PASS | Claude via the Anthropic API. Real calls: Sonnet 5.5 1.4 s, Haiku 5.5 1.4 s. Prod `/health` shows `anthropic_key_configured: true`; the prod Claude review takes 14–16 s |
| D-021 | P2 | LLM | Fallback chain synthesised `groq/claude-…`, a model that exists nowhere | The `<provider>/<model-name>` rule | PASS | Explicit `LLM__FALLBACK_MODELS`; `test_llm_anthropic.py` |
| D-022 | P2 | Tests | 10 backend tests passed only with a developer's `.env` (gateway URL, gpt default) | Non-hermetic settings | PASS | Conftest pins the test LLM env; gateway tests configure their own. Reproduced and fixed in a clean container |
| D-023 | P1 | Tests / Docker | spaCy model load crashed on Linux (`OverflowError: … C ssize_t`), so the PII gate failed closed | `preshed` 3.0.14 is incompatible with spaCy 3.8.16 | PASS | Bisected in clean containers (3.0.13 works, 3.0.14 fails); pinned `preshed<3.0.14` |
| D-024 | P2 | Matching | "A/B tests" / "A/B test" not recognised as experimentation | Missing aliases | PASS | Test in `test_resume_check_core.py` |
| D-025 | P2 | UX | FastAPI 422 validation messages replaced by "An unexpected error occurred" | The interceptor read only a string `detail` | PASS | The message reaches the user (checker page test) |
| D-026 | P1 | Automation | Nothing scheduled ran in production: no new-job discovery unless the owner pressed Search | No worker or cron on Vercel | PASS (code + config) · NOT RUN (first scheduled run is 07:00 UTC) | Vercel Cron `0 7 * * *` → `/internal/cron/daily` (discovery → inbox sync → digest); `CRON_SECRET` set; 6 tests |
| D-027 | P1 | Notifications | No in-app notifications; Gmail emails only for confirmed submissions | Not built | PASS (in-app) · BLOCKED (email: the owner must connect Gmail) | Notifications table migrated in prod; bell and feed; 15 + 6 tests |
| D-028 | P1 | Tailoring | "Tailor for this application" returned 422 on every fresh instance (CI, cold Vercel) | Output folder `<tmp>/cvilwar-tailored` never created; passed only on a dev box where it already existed | PASS | `tailor_pdf` creates it; regression test on a brand-new temp dir fails on the old code |
| D-029 | P2 | Notifications UI | Panel ran off-screen at 320/375 px | Anchored under the bell, which is not at the right edge | PASS | Pinned to the viewport ≤640 px; measured inside at 320/375/720/1440 |
| D-030 | P2 | Assistant UI | Replies showed raw markdown (`**Best matches**`) | Plain-text bubble | PASS | `RichText` renderer; injection test |
| D-031 | P3 | Local stack | `docker compose up` failed when another project held port 6379 | Fixed host ports | PASS | `API_HOST_PORT`/`WEB_HOST_PORT`/`REDIS_HOST_PORT`; clean-clone stack healthy |

| D-032 | P1 | Platforms | **Connect failed for every login portal in production** (Reed, LinkedIn, Indeed…): `No module named 'playwright'` | The sign-in window was launched by the API process, and Vercel has no browser. The attempt also lived in one instance's memory, so a poll landing on another instance lost it | PASS (code) · BLOCKED (owner runs the host) | Production queues the request in `platform_sessions`; the DB-queue worker on the owner's PC opens the window (`db-worker.ps1 -Start -ConnectOnly`). Reproduced on prod before the fix; 16 tests in `test_connect_queue.py` |
| D-033 | P1 | Platforms | A completed sign-in could never be saved | `_persist` imported `get_session_factory`, which does not exist | PASS | `test_persist_stores_the_capture` |
| D-034 | P2 | Platforms | A stored session still showed "NOT CONNECTED" | `import_session` never set `state`, so a first connection stayed at `not_connected` | PASS | `test_settings_shows_the_platform_connected` |
| D-035 | P2 | Platforms | Adzuna offered Connect, and the server rejected it with a 422 | An API-key source was treated as needing a login | PASS | Connect disabled with the reason ("API key, no sign-in"); test |
| D-036 | P3 | Platforms | Test on Indeed/Glassdoor showed `'IndeedPlatform' object has no attribute 'health_check'` | The browser-scraper adapters predate `health_check` | PASS | The registry's offline reason is reported instead; test |
