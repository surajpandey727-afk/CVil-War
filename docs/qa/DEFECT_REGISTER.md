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

### 2026-10-26 — "I can't action, I can't proceed" and the codebase-wide dead-end sweep

Found from the owner's Applications screenshots, then by three independent reviews (backend state machine, frontend dead ends, dead code and config). Every row below has a regression test; "fails on old code" was checked for the core loop fixes.

| ID | Sev | Area | Defect | Root cause | Status | Verification |
|---|---|---|---|---|---|---|
| D-037 | P1 | Automation | **Approve looped forever**: every approval went back to Needs action | The worker re-ran the policy gate after approval and treated "a person should look" (first run on a portal, ATS below threshold, high salary) as a new question | PASS | Approval is stored on the application and waives review questions and the ATS-threshold hold; blocks and pacing holds still apply. `TestApprovalSticks` (3 fail on old code) |
| D-038 | P1 | Automation | A missing sign-in marked the application FAILED | `ApplyPrerequisiteError` fell into the generic failure path | PASS | Stays `approved` with "Waiting for setup: …", one timeline entry per reason |
| D-039 | P0 | Automation | A withdrawn application could still be submitted (and a hold un-withdrew it) | The worker ran a snapshot of ids minutes later and checked only `APPLIED` | PASS | Runs only `queued`/`approved`; `TestOnlyRunnableRowsRun` |
| D-040 | P0 | Automation | "Resume" accepted any status, so a stale click re-submitted applied/withdrawn rows | No status guard | PASS | 409 unless paused at a check; test |
| D-041 | P0 | Automation | A review-mode application could be submitted without approval | Created `queued`, corrected to `pending_review` in a later commit | PASS | Created in its final status; worker sends unapproved review rows back for approval |
| D-042 | P1 | Automation | Every live apply in production ended FAILED | The per-submission confirmation needs pub/sub; the DB-queue worker has none | PASS | An approval is the confirmation; unapproved goes back for approval (`ApprovalRequiredError`) |
| D-043 | P1 | Automation | `APPLYING` had no way out (PC asleep, transient error, crash) | `Retry` escaped the worker pass; no sweep | PASS | No-arq transient errors re-queue; per-row crash isolation; runs older than 45 min go back to the owner (not retried blind: may have submitted) |
| D-044 | P1 | LLM | The browser agent sent Claude model ids to OpenAI | `build_apply_llm` only knew Bedrock and OpenAI | PASS | Anthropic models use browser-use `ChatAnthropic` with `ANTHROPIC_API_KEY`; gateway models use the gateway |
| D-045 | P2 | LLM | Résumé planning defaulted to a gateway-only model id | `plan_model = openai/auto/claude-sonnet` | PASS | Empty = the default model |
| D-046 | P1 | Applications UI | One banner said "no job board connected" beside "65 sources enabled"; rows said nothing about what they waited for | Discovery and submission conflated | PASS | Per-row next step (approval / sign-in / automation host / hold / paused), "Open posting", "I applied myself", Resume; banner counts each blocker |
| D-047 | P1 | Applications UI | A CAPTCHA-paused row could not be resumed; Approve re-hit the same wall | Resume lived in a pop-up production never triggers; approval re-ran headless | PASS | Approve/Resume retry in a visible window and clear the pause |
| D-048 | P2 | Settings | The Apply mode setting was ignored | Every screen sent `apply_mode: review` | PASS | Omitted mode uses the owner's setting |
| D-049 | P2 | Settings | Settings and Sources disagreed on what "enabled" means; one click could cut discovery to one source | Empty list meant "none" in Settings, "all" elsewhere | PASS | Empty = every usable source everywhere |
| D-050 | P2 | Dashboard | Approved applications counted nowhere; rehearsal runs counted as sent | No `approved` count; simulated not excluded | PASS | `applications_approved`, `applications_simulated` |
| D-051 | P2 | Comms | Interview invites detected in email produced no notification and no status change; common phrasings missed | No mapping; classifier gaps | PASS | Notifies; moves applied → interview / → rejected; phrases added |
| D-052 | P2 | Comms | Inbox sync dropped mail beyond 30 messages a day | One page, no `nextPageToken` | PASS | Pages up to 300 |
| D-053 | P2 | Notifications | A second, different "needs you" never notified | Dedup key ignored what happened | PASS | Key includes the occurrence |
| D-054 | P2 | Platforms | A sign-in whose host died stayed "window open" forever and hid a working session | Never expired | PASS | Expired on read; a still-valid session is restored |
| D-055 | P2 | Platforms | Expired sessions surfaced as CAPTCHA pauses; expiry came from a 1-day tracking cookie | No check; earliest of all cookies | PASS | Checked before the browser opens; expiry from the sign-in cookie |
| D-056 | P2 | Automation | Cover letters were generated and never used; the agent always opened the advert | Not passed; `get_application_url` had no caller | PASS | Cover letter offered for upload; apply-form URL stored and used |
| D-057 | P2 | UX | Status pill could never read "All connected"; "Agent active" pulsed with no worker | Read a key nothing writes; static label | PASS | Agent row reads `apply_mode`; server email is informational; sidebar shows real counts |
| D-058 | P2 | UX | Drawer printed raw codes (`connect_platform`) and disabled Apply | No mapping | PASS | Words + links; queueing allowed |
| D-059 | P2 | UX | Applications loaded only 100 rows; "Approve all" released rows with no résumé | Single page; no filter | PASS | All pages; no-résumé rows skipped |
| D-060 | P3 | UX | `/settings?section=platforms` never scrolled; errors and failed saves were silent | Effect ran before render; handlers dropped `detail` | PASS | Tests |
| D-061 | P3 | Timeline | A held row added identical entries every 15 minutes | Recorded every pass | PASS | Recorded only when the reason changes |
| D-062 | P3 | Config | Stale config: schema builder stamped an old head; env examples described OpenAI and job-board passwords; self-hosted Dockerfiles on 3.11 without constraints; port 3000 defaults; README links to missing docs | Drift | PASS | Fixed; ARCHITECTURE.md carries a current-state summary |
| D-063 | P2 | Worker | The PC worker inherited a local `.env` pointing at a deleted storage project and a local gateway model | No production overrides | PASS | `--prod` takes `PROD_SUPABASE_*` and Claude, and refuses to start without them |
