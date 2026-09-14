# Deployment — Vercel + Supabase

Live as of 2026-09-14.

| Piece | URL |
| --- | --- |
| App | https://cvil-war.vercel.app |
| API | https://cvil-war-api.vercel.app |
| Database | Supabase Postgres, project `ongxvurkzbkebbnxroje` |
| Repository | https://github.com/surajpandey727-afk/CVil-War |

Two Vercel projects: `cvil-war` (React/Vite, root `frontend/`) and `cvil-war-api`
(FastAPI on the Python runtime, root `backend/`).

## Request path

The browser only ever talks to its own origin. `frontend/vercel.json` rewrites
`/api/*` to the API deployment, so the client keeps the single relative base URL
it already uses behind Vite's dev proxy and there is no CORS configuration to
maintain or get wrong.

    browser -> cvil-war.vercel.app -> /api/(.*) -> cvil-war-api.vercel.app -> Supabase

Two rewrite rules in that file are load-bearing and easy to break:

- The API rule is a **regex** (`/api/(.*)`), not the `:path*` segment matcher.
  `:path*` does not match a trailing slash, so `/api/v1/jobs/` — the form
  FastAPI's routers use — missed the rule, fell through to the SPA catch-all and
  returned `index.html` with a `200`. Every list endpoint served the HTML shell.
- The catch-all `/(.*) -> /index.html` must stay. Declaring any `rewrites`
  array *replaces* the Vite preset's SPA fallback rather than adding to it, and
  without it every deep link and browser refresh returns Vercel's 404.

## What runs here, and what does not

Serverless functions cannot install system libraries, cannot hold a browser, and
are frozen between requests. Four dependencies are therefore excluded from
`backend/requirements.txt`, and every one of them is already imported lazily in
the application, so the API starts and the features that need them degrade.

| Capability | Status on Vercel | Why |
| --- | --- | --- |
| Auth, jobs, applications, résumés, settings, analytics, sources | Works | Plain DB reads and writes |
| Job discovery from the keyless/API sources | Works | Reed, Adzuna and Apollo keys are set and reachable |
| ATS keyword scoring | Degraded | `spacy` + `en_core_web_sm` do not fit a serverless bundle |
| Résumé PDF rendering | Unavailable | `weasyprint` needs Pango/Cairo, which cannot be apt-installed |
| Live browser apply | Unavailable | `playwright`/`browser-use` need Chromium |
| Background apply queue | Unavailable | `arq` needs a persistent worker and Redis |
| Live run console (WebSocket) | Unavailable | Serverless has no long-lived connection |
| LLM features (fit analysis, cover letters, tailoring) | Unavailable | `LLM__API_BASE` is OmniRoute on `localhost`, unreachable from any cloud host |
| Uploaded file storage | Ephemeral | `STORAGE__LOCAL_ROOT` is `/tmp`, wiped between invocations |

The container images under `docker/` are unchanged and remain the full-capability
deployment. Nothing here forks the application.

## Two things that only bite in the cloud

**The database host is IPv6-only.** `db.<ref>.supabase.co` resolves to an AAAA
record and nothing else; Vercel functions are IPv4-only, so the same credentials
that work locally produced `db: false` on `/health`. Production connects through
the Supavisor pooler instead:

    postgresql+asyncpg://postgres.<ref>:<pw>@aws-1-eu-west-1.pooler.supabase.com:6543/postgres

Transaction-mode pooling hands a connection to a different client between
statements, so asyncpg's prepared-statement cache is disabled on that path
(`app/db/session.py`). The same module selects `NullPool` when running
serverless: a pooled socket in a function that freezes after responding is
either dead when it thaws or held against the database's connection limit by a
process that will never use it again.

**Rate limiting has no Redis.** The limiter previously failed closed in
production, which on this deployment meant every login returned `429` and nobody
could sign in. It now falls back to a per-process fixed window — weaker than a
shared counter, logged once as `ratelimit_degraded_no_redis`, and still a real
limit rather than an outage. Outside production the original behaviour is
unchanged. Provisioning `REDIS_URL` restores shared limits.

## Deploying an update

    cd backend  && vercel deploy --prod --yes      # API
    cd frontend && vercel deploy --prod --yes      # app

`backend/.vercelignore` excludes `pyproject.toml` deliberately: Vercel's Python
builder prefers it over `requirements.txt`, and building from it pulled the full
container dependency set into an 818 MB bundle against a 500 MB ceiling.
`.python-version` pins the interpreter now that pyproject cannot.

Both `.vercelignore` files exclude `.env*`. Vercel uploads the working directory
rather than the git index, so a file ignored only by `.gitignore` still ships.

## Restoring full capability

Everything in the "unavailable" rows needs a host that runs a process rather than
a function. The existing `docker/Dockerfile.api` and `docker/Dockerfile.worker`
run as-is on Railway, Render or Fly.io; point `DATABASE_URL` at the same Supabase
pooler, add a Redis instance, and set `LLM__API_BASE` to a gateway reachable from
that host. The frontend can stay on Vercel — only the rewrite destination in
`frontend/vercel.json` changes.

## Verification performed

- `/health` returns `200` with `db: true`
- Login returns `401` for bad credentials and a JWT for good ones, end to end
  from a real browser through the proxy
- `/api/v1/{jobs,sources,applications,resumes,settings,analytics}` all return
  JSON; the source registry reports 85 catalogued, 65 live
- Deep links (`/login`) and refreshes resolve through the SPA fallback
- Backend suite: 1519 passed, 2 skipped, 1 xfailed
