# CVil-War — Architecture Assessment & Infrastructure Audit

**Date:** 2026-10-17
**Commit audited:** `92d64c1`
**Method:** read of the source tree, plus live probes against the production deployment.
Everything stated as fact here was observed, not recalled. Where I could not verify
something, §17 says so rather than filling the gap.

---

## 1. Executive summary

CVil-War is a personal AI career operating system: a FastAPI/Postgres backend and a React SPA
that discover UK job postings across 85 catalogued sources, score them against the owner's CV,
tailor the CV per posting under a no-fabrication constraint, and optionally drive the
application. It runs on two Vercel projects against a Supabase Postgres instance, under a
hard zero-spend constraint that is enforced in code rather than merely intended.

The engineering is above the bar for a personal project — genuine multi-tenancy, envelope
encryption, refresh-token reuse detection, 1,700+ backend tests, and an unusually honest
habit of making degraded states visible instead of hiding them.

**The production deployment is currently down.** Not degraded — down. The Supabase project
backing it no longer resolves in DNS, so every authenticated request fails. The frontend still
loads, which makes the outage look like a login problem rather than a dead database. This is
the single finding that matters and §2 covers it first.

The architecture also carries one structural gap that is easy to miss: **nothing scheduled
runs in production.** The whole async tier — job discovery, inbox sync, account purge, sponsor
register refresh — lives in an `arq` worker that is only deployed in the Docker profile.
On Vercel there is no worker, no Redis and no cron, so the system is a request/response app
that discovers jobs only when you press the button.

---

## 2. P0 — Production is down

### Evidence

```
GET https://cvil-war-api.vercel.app/health        -> 503
  {"status":"unavailable","db":false,"redis":false,
   "llm_gateway":{"reachable":false,"error":"Skipped — database is unavailable"}}
  (3 consecutive samples, identical — not a cold-start blip)

POST https://cvil-war-api.vercel.app/api/v1/auth/login  -> 500 Internal Server Error
GET  https://cvil-war.vercel.app/                       -> 200  (static SPA, unaffected)
```

`/health` runs a real `SELECT 1` against the engine, so `db:false` is a genuine connection
failure rather than a reporting artefact.

### Root cause

The Supabase project behind it is gone:

```
nslookup db.ongxvurkzbkebbnxroje.supabase.co   -> NXDOMAIN (non-existent domain)
curl    https://ongxvurkzbkebbnxroje.supabase.co/rest/v1/  -> no response (exit 000)
nslookup aws-1-eu-west-1.pooler.supabase.com   -> resolves fine (54.247.26.119, 54.229.189.117)
```

The shared Supavisor pooler resolves, so this is not a DNS or network problem at my end, and
not a Supabase-wide outage. Both hostnames specific to project ref `ongxvurkzbkebbnxroje` are
unreachable, which means that project no longer exists as a running instance.

The most likely cause is the Supabase free tier, which pauses a project after a period of
inactivity and tears down its database host. The last deployment was 2026-09-29 and the last
commit 2026-10-05, so a fortnight of no traffic fits. I cannot confirm *which* of paused,
deleted or migrated it is without the Supabase dashboard — that check is yours.

### Blast radius

Everything except the static shell. All 107 API operations either 401 (auth short-circuits
before touching the DB) or 500. No data loss is implied by the symptom itself — a paused
project retains its data — but that is an assumption until the dashboard confirms it.

### What the user sees

The SPA loads, renders, and redirects to `/login`. Signing in returns a 500. Nothing on screen
says "the database is unreachable", so the failure presents as a broken login rather than an
infrastructure outage. Worth fixing on its own merits: `services/api.ts` could surface a 5xx
on `/auth/login` as an outage rather than a credential error.

### Recovery

1. Open the Supabase dashboard and check project `ongxvurkzbkebbnxroje`. If paused, resume it.
2. If it was deleted, create a new project and run `alembic upgrade head` (20 migrations).
3. Re-point `DATABASE_URL` on the `cvil-war-api` Vercel project at the new **pooler** host
   (`aws-1-eu-west-1.pooler.supabase.com:6543`), not `db.<ref>.supabase.co` — the direct host
   is IPv6-only and Vercel functions are IPv4-only. URL-encode the password.
4. Redeploy and confirm `/health` returns 200 with `db:true`.

One durable fix is worth more than the recovery: a free uptime check on `/health` would have
told you within minutes. The endpoint already returns 503 correctly for exactly this purpose —
nothing is watching it.

---

## 3. Topology — what actually runs where

```
┌─ Browser ───────────────────────────────────────────────────────────────────┐
│  React 18 SPA · Vite 5 · TanStack Query 5 · Zustand 4 · axios               │
│  bundle: 655.7 kB JS (175.7 kB gzip) + 20.6 kB CSS, single chunk           │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────────────────────────┐
│  Vercel project 1: "cvil-war"  →  cvil-war.vercel.app                       │
│  Static CDN (dist/) + rewrites:                                             │
│     /api/(.*)  →  https://cvil-war-api.vercel.app/api/$1                    │
│     /health    →  https://cvil-war-api.vercel.app/health                    │
│     /(.*)      →  /index.html        (SPA fallback)                         │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │ server-side rewrite (same-origin to the browser)
┌──────────────────────────▼──────────────────────────────────────────────────┐
│  Vercel project 2: "cvil-war-api"  →  cvil-war-api.vercel.app               │
│  Python 3.12 serverless function, 1024 MB, maxDuration 60 s                 │
│  routes: /(.*) → api/index.py  (ASGI adapter over app.main:app)             │
│  Region observed: lhr1 → iad1                                               │
│  NO Redis · NO worker · NO cron                                             │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │ asyncpg over TCP:6543, NullPool
┌──────────────────────────▼──────────────────────────────────────────────────┐
│  Supabase Postgres via Supavisor pooler (transaction mode)                  │
│  ** CURRENTLY UNREACHABLE — see §2 **                                       │
└─────────────────────────────────────────────────────────────────────────────┘

Outbound from the function: ~20 external hosts (§9, §11)
```

**Not deployed, but present in the repo:** a full Docker Compose stack (`caddy` + `api` +
`worker` + `redis`) that is the only profile where the async tier runs. See §12.

---

## 4. Request lifecycle, end to end

Take **"search for jobs"** — the path that exercises most of the system.

1. **Browser.** `JobSearchPage` calls `useSearchJobs()` (TanStack Query mutation) →
   `axios` POST `/api/v1/jobs/search` with `{query, location, platforms[], limit}`.
   Base URL is `/api/v1` (same-origin), so no CORS preflight.
2. **Vercel edge, project 1.** `rewrites` matches `/api/(.*)` and proxies server-side to
   project 2. The browser never learns the API is a separate deployment. Note the rewrite
   uses the regex form `/api/(.*)` rather than `:path*` — the latter does not match trailing
   slashes and previously returned the SPA's HTML with a 200 for `/api/v1/jobs/`.
3. **Vercel function, project 2.** `vercel.json` routes everything to `api/index.py`, which
   inserts the bundle root on `sys.path`, sets `STORAGE__LOCAL_ROOT=/tmp/cvilwar-storage`
   (the only writable path in a serverless FS) **before** importing settings, then exports
   `app.main:app`.
4. **FastAPI middleware.** Security headers (`nosniff`, `DENY`, `strict-origin-when-cross-origin`,
   HSTS in prod) → CORS → route.
5. **Auth.** `CurrentUser` decodes the HS256 access token (15-minute lifetime).
6. **Rate limit.** `/jobs` carries `rate_limit(30, 60)`. Redis-backed; with no Redis it falls
   back to a per-process in-memory window, which on serverless means per-instance — see §14.
7. **Tenant scoping.** `get_tenant_db` sets the `current_user_id` ContextVar; a
   `do_orm_execute` listener injects `WHERE user_id = :uid` into every ORM SELECT on a
   `TenantMixin` entity, including lazy loads. Scoping is the default; you must opt out.
8. **Service.** `services/job_search.py` fans out across the selected source adapters,
   each enforcing `CostType.FREE` under `ZERO_COST_MODE`.
9. **Dedup + persist.** `core/job_discovery/dedup.py` (union-find over normalised
   title/company) collapses cross-source duplicates; survivors are upserted against
   `uq_job_platform_id (user_id, platform, platform_job_id)`.
10. **Response.** `JobListingResponse` derives the canonical fields at serialisation time —
    `salary_min/max/currency/period/annualised` from `core/salary.py`, and `sponsorship_status`
    from the five-way `SponsorConfidence` grade.
11. **Database.** asyncpg → Supavisor:6543. `NullPool` (a pooled socket in a frozen function
    is either dead or holding a slot) and `statement_cache_size=0` (transaction-mode pooling
    hands the connection to another client between statements, so server-side prepared
    statements collide by name).

**"Apply to a job"** diverges at step 8 and is where the missing worker shows:
`dispatch_for_mode` checks for an `arq` pool; finding none, it runs `run_apply_pipeline`
**inline, inside the HTTP request**, against the 60-second function ceiling. This is a
deliberate, documented choice — the alternative was a 200 response for work that silently
never happened — but it means a slow apply is a timed-out request. See §11.

---

## 5. Stack inventory

### Backend — serverless profile (`requirements.txt`, 30 packages)

| Layer | Choice |
|---|---|
| Runtime | Python 3.12 (`.python-version`) |
| Framework | FastAPI ≥0.111, Pydantic v2, pydantic-settings |
| ORM / DB | SQLAlchemy 2.0 async, asyncpg, aiosqlite (tests), Alembic + alembic-postgresql-enum |
| Queue | `arq`, `redis[hiredis]` — present but inert on Vercel |
| LLM | LiteLLM ≥1.96 <2, portkey-ai, langgraph ≥1.2 <2 |
| Documents | python-docx, pypdf, pdfplumber, jinja2 |
| HTTP | httpx, beautifulsoup4, tenacity |
| Auth / crypto | PyJWT, `pwdlib[argon2]`, cryptography ≥43 |
| Observability | structlog, prometheus-client |
| Search | exa-py |

### Backend — container profile (`pyproject.toml`, superset)

Adds Playwright + browser-use (live apply), spaCy (ATS keyword scoring), WeasyPrint (PDF
render), and the in-place PDF edit stack (pypdfium2, reportlab, fontTools, numpy).

**This split is load-bearing, not incidental.** Vercel's Python builder prefers
`pyproject.toml` over `requirements.txt` when both are present; the full set built an **818 MB
bundle against a 500 MB ceiling**. `.vercelignore` excludes `pyproject.toml`, `alembic.ini`
and `alembic/` from the upload so `requirements.txt` becomes authoritative, and
`.python-version` pins the interpreter that `pyproject` can no longer declare.

Everything excluded is imported lazily, so its absence degrades a feature rather than
preventing boot. Commit `dff5d78` ("import numpy/pypdfium2 lazily so the API boots without
the PDF render stack") is the scar from getting that wrong once.

### Frontend (7 runtime deps)

React 18, React Router 6, TanStack Query 5, Zustand 4 (+ `persist`), axios, geist.
Dev: Vite 5, TypeScript 5.3, Vitest 1.6, Testing Library, **MSW 2 with
`onUnhandledRequest: 'error'`** — an un-mocked call fails the test rather than silently
hitting the network. No CSS framework; styles are inline objects plus CSS custom properties.

### Repository scale

| Area | Files | Lines |
|---|---:|---:|
| `backend/app` | 285 | 48,349 |
| `backend/tests` | 142 | 24,954 |
| `frontend/src` | 185 | 25,444 |
| `docs` | 7 | ~1,500 |

---

## 6. Data layer

**27 tables** across 20 model modules, 20 Alembic migrations, UUID (32-char) primary keys,
`created_at`/`updated_at` on everything.

### Tenancy

`TenantMixin` adds an indexed `user_id` FK with `ON DELETE CASCADE`. 17 of 27 tables carry it.
The enforcement mechanism (`db/tenant.py`) is the strongest single design decision in the
codebase: scoping is the **default** for ORM SELECTs, and the documented caveats —
SELECT-only, bulk UPDATE/DELETE need explicit predicates, worker paths must set the
ContextVar — each have a regression test. There is a dedicated
`tests/integration/test_tenant_isolation.py`.

Tables deliberately **not** tenant-scoped: `users`, `refresh_tokens`, `password_reset_tokens`,
`platform_sessions`, `user_credentials`, `user_llm_configs`, `user_settings` (keyed by user
directly), plus `domain_skills` / `skill_feedback` / `system_issues` (cross-tenant learning
and ops).

### Domain groupings

- **Identity:** `users`, `refresh_tokens`, `password_reset_tokens`, `user_credentials`,
  `user_settings`, `user_llm_configs`, `platform_sessions`
- **Discovery:** `jobs` (with `canonical_job_id`, `content_hash`, `first/last/last_checked_at`
  for incremental re-fetch, `posting_data` JSON, `sponsor_confidence` + `sponsor_evidence`)
- **Résumé:** `resumes`, `resume_branches`, `resume_versions`, `resume_changes`,
  `job_resume_analyses`, `documents`, `document_versions`
- **Applications:** `applications`, `application_events`, `fit_analyses`
- **Agent ops / learning harness:** `agent_runs`, `run_trajectories`, `run_verdicts`,
  `run_diagnoses`, `domain_skills`, `skill_feedback`, `system_issues`
- **Comms & cost:** `communication_events`, `llm_usage`

### Notable modelling choices

`jobs.posting_data` is deliberately per-source JSON rather than a flattened schema —
"flattening LinkedIn's vocabulary and Greenhouse's into one fixed schema would mean inventing
values neither of them supplied." `enriched_at IS NULL` means *never fetched*, which the UI
renders differently from *fetched and found nothing*. That distinction is maintained all the
way to the job card.

---

## 7. Identity & access

- **Passwords:** `pwdlib` `PasswordHash.recommended()` → Argon2.
- **Access token:** HS256 JWT, **15 minutes**.
- **Refresh token:** 30 days, httpOnly cookie, hashed at rest, **rotating with family-based
  reuse detection** — presenting a retired token revokes the entire family. Implemented as a
  conditional UPDATE whose rowcount decides, so the race is handled at the database rather
  than in Python. `tests/integration/test_auth.py::TestRefreshFlow::test_reuse_detection_revokes_family`
  pins it.
- **WebSocket:** separate 60-second `ws_ticket` token type, validated **before** `accept()`.
  Typed tokens (`expected_type=`) prevent an access token being replayed as a WS ticket.
- **Admin:** `require_superuser` at router level on `/admin`.
- **Internal webhook:** static bearer compared with `hmac.compare_digest`, fails closed when
  unset. This is the n8n trigger surface for discovery and inbox sync.
- **Rate limits:** auth 5/min; jobs, resumes, applications 30/min; resume-intelligence 20/min;
  communications 10/min.

---

## 8. Secrets & encryption

Envelope encryption via a `SecretsProvider` interface with local and KMS implementations.

Per secret: a fresh Fernet **DEK** encrypts the plaintext; the DEK is wrapped by the app
**KEK**. The KEK is a `MultiFernet` over `SECRETS__APP_KEYS`, so rotation is "prepend a new
key" — old blobs still decrypt, and `CredentialStore.rotate()` re-wraps rows to the current
KEK, skipping ones already current. `kek_id` is stored per blob so rotation is observable.

This protects `user_credentials` (third-party platform logins) and `user_llm_configs`
(per-user LLM keys). Production start-up refuses to boot on insecure config —
`validate_production_settings` raises if the JWT key is still the dev default or the storage
signing secret is unset.

---

## 9. Job discovery

**85 catalogued sources.** Live breakdown from the registry:

| Health | Count |
|---|---:|
| `live` | 65 |
| `not_implemented` | 13 |
| `degraded` | 2 |
| `auth_required` | 2 |
| `unavailable` | 2 |
| `interactive_available` | 1 |

By tier: 68 company career pages, 8 UK job boards, 5 tech/startup aggregators, 4 Tier-1
browser-automation platforms.

Adapters live in `core/job_discovery/sources/`: `boards.py` (Remotive, Jobicy, Arbeitnow,
RemoteOK), `uk_boards.py` (Reed, Adzuna), `uk_visa_boards.py` (MoveJobs, Tarve — sponsorship-
framed), `ats.py` (Greenhouse, Lever, Ashby, SmartRecruiters — the 68 career pages are
instances of four ATS adapters, which is why that number is large without being 68 separate
integrations), `linkedin.py` (degraded — the browser-use API it targeted no longer exists),
and `exa_search.py` (semantic, needs a key).

**Sponsorship classification** (`core/sponsorship/`) grades each posting across the UK Home
Office licensed-sponsor register, explicit sponsorship language, and explicit *negation* —
reported as `NOT_SPONSOR` rather than collapsed into `UNKNOWN`, because "the posting says it
won't sponsor" is actionable where silence is not. A ranking boost by default, a hard filter
only via `AutomationPolicy.exclude_no_sponsorship`.

**Dedup** is union-find over normalised title/company with Jaccard title matching, so the same
role found via Reed, Adzuna and the employer's Greenhouse board collapses to one row.

---

## 10. Résumé & ATS subsystems

Two ATS implementations coexist:

- `core/ats/` — spaCy-based (keyword analyser, skill matcher, experience analyser, impact
  matrix, optimiser). **Degrades to regex without spaCy, which is the state on Vercel.**
- `core/ats_engine/` — the newer deterministic, component-scored engine (parsing, matching,
  requirements, scoring, structure, taxonomy, shortlist, report).

`core/resume_tailoring/` is 25 modules and the most intricate part of the system: a document
model where **bullets are the only editable unit**, so preservation is a property of the
representation rather than a rule anyone can forget. `extract.py` carries typography (font
family, size, weight, colour, alignment, spacing, page margins) off the source PDF;
`render.py` reapplies it; `validate.py` runs 11 checks (fabricated metric, unsupported
technology, AI language, unsupported claim, asserted ownership, keyword loss, appended clause,
claim escalation, excessive expansion, vague evidence, no-op) and **fails closed** — a plan
that does not validate returns the original document unchanged. A 13-module `pdf_*` subsystem
does in-place PDF editing on a deliberately permissive licence stack (the AGPL PyMuPDF is
explicitly not a dependency — see `docs/PDF_STACK_LICENSES.md`).

---

## 11. Async tier — the structural gap

`WorkerSettings` (arq) defines five scheduled jobs:

| Job | Schedule |
|---|---|
| `monitor_system_health` | every 15 min |
| `run_discovery_for_all_users` | every `DISCOVERY_INTERVAL_MINUTES` (default 30) |
| `run_inbox_sync_for_all_users` | hourly |
| `purge_deleted_accounts` | daily 03:30 |
| `refresh_sponsor_register` | Mondays 04:00 |

**None of them run in production.** The worker is a separate process; Vercel hosts one
function, there is no `crons` key in either `vercel.json`, and `/health` reports
`redis:false`. Consequences:

- Job discovery is manual only. The "always-on agent" is on-demand.
- Gmail inbox sync never runs on its own.
- Soft-deleted accounts are never purged — a GDPR-adjacent commitment the code makes and the
  deployment does not keep.
- The sponsor register goes stale, which quietly degrades sponsorship classification.
- `monitor_system_health` — the thing that would have caught §2 — does not run.

The apply path is handled well: no queue means `dispatch_for_mode` runs the pipeline inline
rather than returning a false 200. But inline work is bounded by `maxDuration: 60`, and the
real apply pipeline wants Chromium, which the serverless bundle does not carry. Live apply is
a container-profile feature.

**Cheap fixes, in order of value:** Vercel Cron (free tier: 2 jobs) hitting the existing
`/api/v1/internal/*` webhook endpoints would restore discovery and inbox sync without a
worker. Upstash Redis has a free tier that would restore real queuing and cross-instance rate
limiting.

---

## 12. The two deployment profiles

| | Vercel (live) | Docker Compose (repo only) |
|---|---|---|
| API | 1 serverless function | `Dockerfile.api` behind Caddy |
| Worker | — | `Dockerfile.worker` (arq) |
| Redis | — | `redis:7-alpine` |
| TLS | Vercel-managed | Caddy automatic |
| Browser automation | no | yes (Playwright) |
| spaCy ATS | no (regex fallback) | yes |
| WeasyPrint PDF | no | yes |
| Scheduled jobs | none | all five |
| File storage | `/tmp` (ephemeral) | volume |

The serverless profile is a genuine subset, not a different system — one `app.main:app`,
deployed two ways. That is the right call. The risk is that the repo's own
`ARCHITECTURE.md` documents only the container profile (§16, item 4).

---

## 13. Observability

- **Logging:** structlog, JSON in production.
- **Metrics:** prometheus-client — applications, ATS score histogram, LLM latency/tokens/cost,
  browser actions, queue depth, queue processing duration, documents generated, job searches,
  jobs found. `/metrics` is open in non-prod and **requires a bearer token in production,
  failing closed when `METRICS_TOKEN` is unset**.
- **Errors:** Sentry, no-op unless `SENTRY_DSN` is set.
- **Health:** `/health` is a genuinely good probe — hard-fails on DB (503) and soft-reports
  Redis, the LLM gateway and which external API credentials are configured. It distinguishes
  "the app is up" from "the app is up and its dependencies are reachable".

**The gap is not instrumentation, it is collection.** On Vercel nothing scrapes `/metrics`,
nothing polls `/health`, and Prometheus counters in a serverless function reset on every cold
start, so they measure one invocation. The app is well-instrumented and effectively
unmonitored — which is exactly how §2 went unnoticed for up to a fortnight.

---

## 14. Security posture

**Strong:** Argon2; typed, short-lived JWTs; refresh rotation with family revocation;
constant-time webhook comparison; envelope encryption with rotation; default-on tenant
scoping; fail-fast production config validation; security headers independent of the proxy;
metrics auth failing closed; docs/redoc disabled in production; no `dangerouslySetInnerHTML`
anywhere in the frontend; `.vercelignore` excluding `.env` from the upload (Vercel ships the
working directory, not the git index — `.gitignore` alone would not have protected it).

**Weaknesses, honestly stated:**

1. **Rate limiting is per-instance without Redis.** `_InProcessWindow` is the fallback, and on
   serverless each concurrent instance keeps its own counter. The 5/min auth limit is
   therefore 5/min *per warm instance*. It logs `ratelimit_degraded_no_redis` once per
   process, so the degradation is at least visible.
2. **Access token in the SPA.** The refresh token is httpOnly; the access token is handled in
   JS and is XSS-reachable. Mitigated by the 15-minute lifetime and no HTML injection sink,
   not eliminated.
3. **No CSP.** `X-Frame-Options` and `nosniff` are set; a Content-Security-Policy header is
   not. For an app that renders third-party job descriptions, that is the gap worth closing
   next.
4. **Local `.env` points at the production database.** Already recorded in memory, and the
   reason this audit's browser verification stopped at the login screen. Any local test run
   that forgets to override `DATABASE_URL` writes to live data.
5. **The KEK lives in an env var** in the local provider. Correct for this scale; the `kms.py`
   interface exists for when it is not.
6. **`/openapi.json` is public.** `/docs` and `/redoc` correctly 404 in production, but the
   schema they read does not:

   ```
   GET /docs         -> 404
   GET /redoc        -> 404
   GET /openapi.json -> 200   <- full schema, unauthenticated
   GET /metrics      -> 401   <- correct, fails closed
   ```

   This is how I enumerated all 107 operations in this audit without credentials. Low
   severity — it discloses shape, not data — but it is inconsistent with the intent behind
   disabling the doc UIs, and `openapi_url=None` in production would close it.

Live-verified during this audit: `/metrics` returns 401 without a token, `/docs` and `/redoc`
are 404, and the security headers (`nosniff`, `DENY`, `strict-origin-when-cross-origin`,
`Strict-Transport-Security: max-age=63072000; includeSubDomains`) are all present on
production responses.

---

## 15. Testing & CI

Both suites were run against the audited commit as part of this audit.

| Suite | Files | Tests | Result | Wall time |
|---|---:|---:|---|---:|
| Frontend (Vitest + MSW) | 50 | 430 | 430 passed | ~2 min |
| Backend (pytest) | 135 | 1,922 | 1,919 passed, 2 skipped, 1 xfailed | 7 m 49 s |

**Backend distribution:** 110 unit, 23 integration, 1 e2e, 1 root. The integration tier runs
against SQLite in-memory (`conftest.py` forces `DATABASE_URL` before any `app.*` import,
specifically so a dev `.env` pointed at real Postgres cannot make the suite open live
connections — the same hazard as §14.4, already defended at the test boundary).

**Frontend distribution:** 19 pages, 17 components, 5 auth, 5 lib, 2 store, 1 services,
1 a11y sweep. MSW runs with `onUnhandledRequest: 'error'`, so an un-mocked call fails the
test rather than silently reaching the network.

**CI** (`.github/workflows/ci.yml`, on push and pull_request) runs two jobs:
- *backend:* Python 3.12 + a Redis service container → ruff → pytest → **pip-audit** for
  dependency vulnerabilities.
- *frontend:* Node 20 → `tsc` → ESLint → Vitest.

CI is genuinely load-bearing here and includes a dependency-vulnerability gate, which is more
than most projects this size carry. What it does *not* do is deploy — Vercel deployments are
driven manually from the CLI, so a green pipeline does not mean the running system matches
`main`. (It does today: the live API carries `/api/v1/communications/gmail/test`, added in the
most recent commit `92d64c1`.)

---

## 16. Technical debt register

Ordered by what I would actually fix first.

| # | Item | Why it matters |
|---|---|---|
| 1 | **Production database gone** (§2) | The app does not work. |
| 2 | **No uptime monitoring** | `/health` already returns 503 correctly. Nothing reads it. One free check closes this permanently. |
| 3 | **No scheduled jobs in prod** (§11) | Discovery, inbox sync, account purge and sponsor refresh never run. Vercel Cron → existing internal webhooks is a small change. |
| 4 | **`ARCHITECTURE.md` is two months stale** | Dated 2026-08-12. Documents Docker/Redis/FAISS, never mentions Vercel or Supabase, and references FAISS vector indices that **do not exist in the codebase** (`grep -rn faiss app/` → nothing). A new reader would build the wrong mental model. |
| 5 | **Two ATS implementations** | `core/ats/` and `core/ats_engine/` coexist. One should win, or the boundary should be documented. |
| 6 | **Frontend ships one 655.7 kB chunk** | 175.7 kB gzipped, over Vite's 500 kB warning. Route-level `React.lazy` would halve first load. |
| 7 | **Jobs list is one page deep** | Fetched at `page=1, size=100`; filters run client-side over that page. Surfaced honestly in the UI ("of N stored"), but server-side filtering is the real fix. See `docs/JOBS_AUDIT.md` §4. |
| 8 | **Per-instance rate limiting** (§14.1) | Upstash free tier resolves it. |
| 9 | **No CSP header** (§14.3) | The app renders third-party job descriptions; this is the next security header worth adding. |
| 10 | **Login shows a credential error for a 5xx** | Turns an outage into a confusing UX. Small frontend change. |
| 11 | **spaCy ATS degrades silently in prod** | The regex fallback is a real behaviour difference between profiles; nothing on screen says which engine produced a score. |
| 12 | **`/openapi.json` public in prod** (§14.6) | Discloses the full API shape although `/docs` is disabled. One-line fix. |
| 13 | **51 pre-existing ruff errors** | In `resume_intelligence`/`resume_tailoring`, inherited from commit `8a9275c`. Not regressions. |

---

## 17. What I could not verify

Stated plainly rather than papered over.

- **Production environment variables.** The Vercel CLI token in this environment has lost
  authorization (`vercel env ls` → "Could not retrieve Project Settings"; `vercel project ls`
  → "Not authorized"). The env surface in §5 and §8 is derived from `config/settings.py`,
  which is authoritative for what the app *requires*, not for what is *set*.
- **Whether the Supabase project is paused or deleted**, and therefore whether the data is
  intact. DNS is gone for both its hostnames; the dashboard is the only way to tell.
- **Any signed-in behaviour.** Verification stopped at the login screen on both local and
  production, because the local API is wired to the production database and I would not
  create an account there or use your credentials. This is consistent with the standing rule
  recorded in memory (E2E on scratch SQLite only).
- **Actual production cost.** The zero-spend constraint is enforced in code
  (`CostType.FREE` + `ZERO_COST_MODE`, refusing to instantiate a billable adapter) and every
  external host in §9 is a free tier or public endpoint, but I have no billing visibility.
  Design intent is verified; the invoice is not.
- **Cold-start latency and real p95.** One sample through `lhr1 → iad1`; not a measurement.

---

## 18. Verdict

The application architecture is sound and in several places genuinely well-made: the tenant
filter, the envelope encryption, the refresh-token family revocation, the
preservation-by-representation résumé model, and a consistent refusal to let a degraded state
look like a healthy one. The test suite is substantial and the comments throughout record
*why* decisions were made, including the failures that motivated them — which is rarer than
it should be.

The weakness is not in the code, it is in the operational envelope around it. A system
designed to run continuously is deployed on a platform that only runs it on request; a system
that is thoroughly instrumented has nothing collecting the instruments; and a database on a
free tier that pauses when idle had nothing watching it when it did.

Fixing items 1–3 in §16 — restore the database, point an uptime check at `/health`, and move
the two most valuable cron jobs onto Vercel Cron — would close the gap between what this
system is built to do and what it currently does. None of the three is a large change.
