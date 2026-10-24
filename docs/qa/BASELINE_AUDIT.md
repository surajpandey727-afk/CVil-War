# Baseline audit — 2026-10-24

Scope: the defects reported from `https://cvil-war.vercel.app/jobs` (non-UK jobs, missing
posting date / city / country, broken layout, "Searching…" never finishing) and the system
they sit in. Statuses used across `docs/qa/`: **PASS / FAIL / BLOCKED / NOT RUN** only.

## System as found

| Layer | Implementation | Notes |
|---|---|---|
| Frontend | React 18 + Vite 5 + TanStack Query 5 + Zustand, hand-rolled design system | Vercel project `cvil-war`, not git-connected; `/api/*` rewritten to the API project |
| API | FastAPI on Vercel Python serverless (`backend/api/index.py`, `maxDuration` 60s) | Vercel project `cvil-war-api` |
| Database | Supabase Postgres, pooler `aws-1-eu-west-3` (6543 transaction / 5432 session) | Alembic head was `a3d9c51e7b20` |
| Discovery | 65 "usable" sources fanned out per search (Reed, Adzuna `/gb/`, LinkedIn guest, Remotive, Jobicy, Arbeitnow, RemoteOK, 56 `careers:*` ATS boards) | `services/job_search.search_jobs` |
| Background work | arq/Redis worker exists in code; **no worker runs in the Vercel deployment** | affects Phases 6–8 |

## Production data at baseline (read-only query, 2026-10-24)

| Measure | Value |
|---|---|
| Stored jobs | 2,143 (1 user) |
| Jobs with a posting date | **0** (all `posted_date` NULL) |
| Jobs with no description | 302 (253 LinkedIn guest cards) |
| Jobs whose own location is outside the UK | 1,039 (48%) |
| Jobs with ambiguous / no usable location | 90 |
| Verified UK-eligible | 1,014 |

## Root causes

1. **No location model.** `Job` stored a free-text `location` and a `remote` bool. Nothing
   recorded a country, so no query could exclude San Francisco, Berlin or Toronto. The global
   ATS boards (`careers:stripe`, `careers:openai`, …) and the remote boards return worldwide
   roles, and every one was stored and listed.
2. **Posting dates dropped at ingestion.** Every adapter parses `posted_at`, but
   `_listing_to_job` never copied it onto the `Job`, so the column was always NULL.
3. **Layout.** The rail was a flex item with `flex: 0 0 268px`. A basis is not a limit: with
   the default `min-width: auto` it grew to the min-content width of its longest unbreakable
   child (non-wrapping source labels such as `careers:databricks`), squeezing the results
   column — exactly the screenshot.
4. **"Searching…" stuck.** Client timeout 30s; server spent up to 20s fetching sources, then
   one `refresh()` round trip per saved row against the remote pooler, then dedup. The client
   gave up first.
5. **Counts disagreed.** The header's "2,179 opportunities" counted every stored row; the
   list could only ever show the UK ones.

## Dependency map (jobs path)

```
JobSearchPage ── useJobs(page, 100, {location, query, workplace}) ── GET /jobs/
   │                                                        └─ services.job_search.list_jobs
   │                                                             ├─ job_location.classify_pending
   │                                                             └─ WHERE uk_eligible AND not-a-listed-duplicate
   ├─ useSearchJobs ── POST /jobs/search ── search_jobs ── 65 sources ── _listing_to_job
   │                                                        ├─ core.dates.parse_posted_at
   │                                                        └─ job_location.stamp ── core.geo.classify
   ├─ LocationRail ── GET /jobs/location-summary
   └─ useAutoScoreJobs ── POST /jobs/score (batches of 25)
Dashboard / pipeline header ── GET /analytics/dashboard (UK-eligible counts)
Skill Radar corpus ── UK-eligible jobs only
```
