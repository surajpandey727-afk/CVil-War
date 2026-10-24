# Regression results — 2026-10-24

| Suite | Command | Result | Status |
|---|---|---|---|
| Backend (all) | `pytest -q` | 2,058 passed, 2 skipped, 1 xfailed, 0 failed (the 422 workplace test was added after this run and passed on its own) | PASS |
| Backend lint | `ruff check app/` · `ruff format --check app/` | clean | PASS |
| Frontend types | `tsc --noEmit` | clean | PASS |
| Frontend lint | `eslint src --max-warnings=0` | clean | PASS |
| Frontend tests | `vitest run` | 53 files, 449 passed, 0 failed | PASS |
| Frontend build | `npm run build` | built (pre-existing >500 kB chunk warning) | PASS |
| Migration on production Postgres | `alembic upgrade head` (session pooler) | `a3d9c51e7b20 → e5b2c8d41f07`, transactional | PASS |
| Backfill idempotence | `reclassify_locations.py` twice | second run `changed: 0` | PASS |
| Live search (local, scratch DB, 65 real sources) | UI | 23.5 s, finished, 2 non-UK rejected at ingestion | PASS |
| Responsive sweep | 320 / 720 / 1100 / 1440 / 1920 px | 0 px horizontal overflow | PASS |
| Backend CI job (GitHub) | `pip install -e .[dev]` | `resolution-too-deep` (pre-existing) | FAIL |

New tests added this pass: `test_uk_location_policy.py` (74), `test_posted_at_parsing.py` (15),
ingestion policy test, 9 jobs-API tests (UK filter, quarantine, summary, workplace incl. 422,
nationwide, response shape, duplicates ×2), dashboard UK-count test; frontend `jobPlace.test.ts`
(10), `JobSearchPage.location.test.tsx` (6), dashboard D-015 test.

Changed existing tests (deliberate contract change, not weakened): fixtures that used a bare
`"Remote"` or blank location now use a UK location, because those rows are correctly
quarantined under the UK-only policy; "no filter returns everything (8)" became "no filter
returns every UK job (5) and nothing else", with a new test proving the other 3 are kept and
reviewable via `include_quarantined=true`.
