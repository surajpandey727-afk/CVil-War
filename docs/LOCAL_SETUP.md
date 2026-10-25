# Local setup — the stack, and the worker that applies for production

Two separate things run on this machine:

1. **The local stack** (Docker Compose): API, frontend, arq worker, Redis, against a local SQLite
   file. For development and for checking changes. Never touches production.
2. **The production worker** (`scripts/db-worker.ps1`): a long-running process that picks up
   applications approved on the live site (cvil-war.vercel.app) straight from the production
   database and runs the apply pipeline with a real browser — the part Vercel cannot host (D-016).

All commands below are PowerShell from the repo root unless noted.

---

## 1. Local stack (Docker)

Prerequisite: Docker Desktop running.

```powershell
docker compose up --build -d      # build + start; first build ~10 min (Chromium, spaCy model)
docker compose ps                 # backend, worker, frontend, redis -> "healthy"; migrate -> exited (0)
docker compose logs -f backend    # follow one service
docker compose down               # stop (data in ./data and the redis volume is kept)
docker compose down -v            # stop and also drop the Redis volume
```

- Frontend: http://localhost:3000 · API: http://localhost:8000/health
- No `.env` is required. Every setting has a local default in `docker-compose.yml`. To configure
  keys, copy `.env.example` to `.env` in the repo root; compose reads it automatically.
- Ports are bound to `127.0.0.1` only.
- Before storing real credentials locally, put a generated key in `.env`. The compose default
  is a public placeholder.
  ```powershell
  backend\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  # .env:  SECRETS__APP_KEYS=<that value>
  ```
- `BROWSER__LIVE_APPLY` defaults to `false` here. A run then records the application as
  **simulated**: no browser runs and nothing is sent to an employer.

### Native backend (no Docker), for tests and debugging

```powershell
cd backend
uv venv .venv ; uv pip install -c constraints.txt -e ".[dev,postgres,aws]"
# or: python -m venv .venv ; .venv\Scripts\pip install -c constraints.txt -e ".[dev,postgres,aws]"
.venv\Scripts\python -m spacy download en_core_web_sm
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\alembic upgrade head
.venv\Scripts\uvicorn app.main:app --reload
```

`constraints.txt` is the uv-compiled resolution of `pyproject.toml`. pip's own resolver fails
on this dependency graph with `resolution-too-deep` (D-013). After changing dependencies,
regenerate it with the command at the top of the file.

---

## 2. The production worker (D-016)

### Decision: the database is the queue (no hosted Redis)

The live API runs on Vercel, which has no worker, no Redis and no browser. There were two free
options. **The worker reads the queue directly from the production database.**

| | Hosted Redis (Upstash free) + arq | **Database as queue (chosen)** |
|---|---|---|
| Extra account / secret | yes (`REDIS_URL`) | none |
| Source of truth | Redis job + DB row, which can disagree | the row's `status` only |
| Worker off for a week | jobs may expire or be evicted | rows wait; nothing is lost |
| Free-tier fit | arq polls continuously and exhausts a daily command quota | one indexed `SELECT` every 30 s |
| Two workers at once | arq dedups by job id | a Postgres advisory lock per application |

How it works:

- With `APPLY_DISPATCH=db_queue` set on the Vercel API, approving an application leaves it at
  `approved`, or `queued` in autonomous mode. Nothing runs inside the HTTP request.
- The worker (`app/workers/db_queue.py`) polls every 30 s for `approved`/`queued` rows, oldest
  first, across all users. For each one it takes `pg_try_advisory_lock` and runs the same
  `run_apply_pipeline` the arq worker uses.
- If a policy HOLD puts a row back to `queued`, the worker backs off from it for 15 minutes.

### Environment (set in your shell, never in a committed file)

| Variable | Needed for | Notes |
|---|---|---|
| `PROD_DATABASE_URL` | always | `postgresql+asyncpg://postgres.<ref>:<url-encoded password>@aws-1-eu-west-3.pooler.supabase.com:5432/postgres`. Use the **session** pooler (5432); advisory locks need a session. |
| `SECRETS__APP_KEYS` | live apply | Must equal the value on the Vercel API, or the worker cannot decrypt the platform sessions and keys stored in production. |
| `ENVIRONMENT` | — | Set `production` once `SECRETS__APP_KEYS` is set. `development` echoes SQL. |
| `BROWSER__LIVE_APPLY` | — | `false` (default) **records the application as applied (simulated) without sending anything.** Only set `true` when you want real submissions; review mode still requires your approval of each one first. |
| `ANTHROPIC_API_KEY` | AI steps | Read only from the environment. |

### Start / stop

```powershell
$env:PROD_DATABASE_URL = '<from Supabase -> Connect -> Session pooler>'
.\scripts\db-worker.ps1 -DryRun     # read-only: lists what WOULD run; writes nothing
.\scripts\db-worker.ps1 -Start      # background; log: backend\data\logs\db-worker.log
.\scripts\db-worker.ps1 -Status
.\scripts\db-worker.ps1 -Stop
```

Foreground, for watching it work:
`cd backend; .venv\Scripts\python scripts\db_worker.py --prod --once` (one pass) or without
`--once` (poll forever; stop with Ctrl+C). Add `--user-id <id>` to process one account only.

**Always run `-DryRun` first.** In simulated mode (`BROWSER__LIVE_APPLY=false`) the worker
still moves each claimed application to `applied`, labelled *simulated*. Point it at production
only when you want that to happen to the rows it lists.

### Connecting Reed, LinkedIn, Indeed… (Settings → Platforms → Connect)

The sign-in window has to open on a machine with a browser and a person in front of it, and
Vercel has neither (every Connect in production used to fail with `No module named
'playwright'`). With `APPLY_DISPATCH=db_queue`, a Connect click is queued in
`platform_sessions` and **this worker opens the platform's real sign-in page on your desktop**.
You sign in there yourself (password, 2FA, any "are you human" check). Only that platform's own
cookies are stored, encrypted with `SECRETS__APP_KEYS`. The Settings dialog follows progress
from the database and closes once the window has done its job.

```powershell
$env:PROD_DATABASE_URL = '<session pooler URL>'
$env:SECRETS__APP_KEYS = '<same value as on the cvil-war-api Vercel project>'
.\scripts\db-worker.ps1 -Start -ConnectOnly   # sign-ins only; never touches applications
# now click Connect on https://cvil-war.vercel.app/settings
```

Shortcut: `.\scripts\start-connect-host.ps1` does all of this in one step. It pulls the two values from Vercel (after `npx vercel login`), never prints them, deletes the temporary file, and starts `-ConnectOnly`.

`-ConnectOnly` is the safe way to connect accounts: the full worker would also process approved
applications (as *simulated* applies unless `BROWSER__LIVE_APPLY=true`). Playwright's Chromium
must be installed in the backend venv (`.venv\Scripts\python -m playwright install chromium`).

Sources with an API key (Adzuna) have nothing to sign in to. Their Connect is disabled with
that explanation, and the server's key is used for search. Adzuna listings send you to the
employer's own site to apply.

### Turning it on in production

```powershell
cd backend
npx vercel env add APPLY_DISPATCH production --value db_queue --yes --token=$env:VERCEL_TOKEN
npx vercel --prod --yes --token=$env:VERCEL_TOKEN
```

Until this is set, the API keeps its old behaviour: an approval runs the pipeline inline, inside
the request, with no browser.

---

## 3. LLM: Claude via the Anthropic API

- Default model `anthropic/claude-sonnet-5-5`. Cheap classification calls (`harness_judge`,
  `profile_extract`, `classify`) use `anthropic/claude-haiku-5-5`. The fallback chain is
  `LLM__FALLBACK_MODELS`, default `["anthropic/claude-haiku-5-5"]`. Add
  `"openai/Full-Send"` there to fall back to the local OmniRoute gateway.
- The key is read **only** from `ANTHROPIC_API_KEY`. `/health` reports `llm.anthropic_key_configured`
  (true/false) and never the value.
- Anthropic calls never go through `LLM__API_BASE`, and omit `temperature` and JSON mode, which
  the 5.5 models reject. JSON is validated by the client instead.
- On Vercel, the existing `LLM__DEFAULT_MODEL=openai/Full-Send` overrides the code default. To
  switch production: add `ANTHROPIC_API_KEY`, then remove `LLM__DEFAULT_MODEL` and
  `LLM__PREFERRED_PROVIDER` (or set them to the Anthropic values), then redeploy.
- One real call to prove the route works:
  `cd backend; .venv\Scripts\python scripts\llm_smoke.py`. It exits 2 (BLOCKED) when the key is
  unset.
