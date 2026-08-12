# AutoApply AI — Project Conventions

## Quick Start
```bash
docker compose up --build        # Start all services
docker compose -f docker-compose.yml -f docker-compose.dev.yml up  # Dev mode with hot reload
```

## Architecture
- Backend: FastAPI (Python 3.11) at `backend/app/`
- Frontend: React + TypeScript at `frontend/src/` — **no MUI**; the UI is a hand-rolled
  design system (`src/styles/theme.css`, `src/components/ui/`). Do not introduce a component
  library; extend the existing one.
- Queue: Redis via **arq** (`arq app.workers.tasks.WorkerSettings`)
- Database: SQLite (default), PostgreSQL optional. Schema is owned by Alembic — the app does
  **not** create tables at startup.

## Environment traps (verified the hard way — see docs/PHASE0_AUDIT.md)
- **Never put the checkout in a OneDrive-synced or deep path.** `python -m venv` fails there,
  and storage keys push paths past Windows' 260-char `MAX_PATH`, breaking résumé upload.
- **`python -m spacy download en_core_web_sm` is required** and is not installed by pip. Without
  it, ATS analysers degrade to regex and the harness PII gate fails closed.
- **WeasyPrint cannot import on Windows** (needs native GTK/Pango). PDF rendering is Docker-only
  there; tests that touch it skip explicitly.
- **`litellm` must stay pinned `>=1.96,<2`.** An open lower-bound range makes pip backtrack to a
  Rust-requiring sdist and the whole install fails on a clean machine.
- **Job discovery is currently broken** — the LinkedIn/Indeed/Glassdoor plugins go through
  `core/automation/agent.py`, which targets the pre-0.2 browser-use API. The maintained browser
  code is `core/automation/runtime/` (apply only).

## Scores are 0–1 in the API
All ATS/match scores are stored and returned on a **0–1 scale**. Multiply by 100 to display
(`lib/status.ts::atsPercent`). Getting this wrong was BUG-003.

## Directory Layout
- `backend/app/config/` — Settings and constants
- `backend/app/core/` — Domain modules (ats/, automation/, documents/, llm/, matching/)
- `backend/app/api/v1/` — FastAPI routes
- `backend/app/services/` — Business logic layer
- `backend/app/models/` — SQLAlchemy models
- `backend/app/schemas/` — Pydantic request/response schemas
- `backend/app/workers/` — Background queue workers
- `frontend/src/` — React SPA

## Coding Standards
- Python: async-first, structlog, Pydantic v2, SQLAlchemy 2.0 Mapped[] annotations
- TypeScript: strict mode, no `any`, React Query for server state, Zustand for UI state
- Max 300 lines per file
- Naming: snake_case (Python), PascalCase components / camelCase hooks (TypeScript)

## Adding a New Platform
1. Create `backend/app/core/automation/platforms/{name}.py`
2. Implement `JobPlatform` ABC (login, search, scrape_details, apply)
3. Register in `platforms/__init__.py`: `platform_registry.register("name", NamePlatform)`

## Adding a Resume Template
1. Create `templates/resume/{name}/template.html` + `style.css`
2. Add template name to `RESUME_TEMPLATES` in `backend/app/config/constants.py`

## Common Commands
```bash
# Backend (first run)
cd backend
pip install -e ".[dev]"
python -m spacy download en_core_web_sm   # required; pip does not fetch it
alembic upgrade head                      # required; app does not create tables
uvicorn app.main:app --reload

# Backend checks
pytest tests/ -v
ruff check app/          # this is the gate; `ruff check tests/` has pre-existing nits
ruff format app/

# Frontend
cd frontend && npm run dev
npm run build
npm run lint
```
