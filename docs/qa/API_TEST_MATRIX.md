# API test matrix — jobs surface

All rows run in CI's pytest suite against SQLite with the tenant filter active.

| Endpoint | Case | Expected | Status |
|---|---|---|---|
| `GET /jobs/` | no filter | only `uk_eligible` rows, total = UK count | PASS |
| `GET /jobs/` | `include_quarantined=true` | every stored row, with status fields | PASS |
| `GET /jobs/` | `location=London` | boroughs, districts, London postcodes; not "United Kingdom"/"Worldwide" | PASS |
| `GET /jobs/` | `location=United Kingdom` | every UK row (no-op filter) | PASS |
| `GET /jobs/` | `workplace=hybrid` | only `workplace_type=hybrid` | PASS |
| `GET /jobs/` | `workplace=bogus` | 422 | PASS (`test_an_unknown_workplace_value_is_rejected`) |
| `GET /jobs/` | linked duplicate | listed once; total counts once | PASS |
| `GET /jobs/` | response shape | `city`, `country_name`, `workplace_type`, `posted_at`, `discovered_at`, `raw_location`, `location_verification_status` present | PASS |
| `GET /jobs/` | row with no posting date | `posted_at: null` — not `created_at` | PASS |
| `GET /jobs/location-summary` | seeded 8 rows | `{total 8, uk_eligible 5, outside_uk 1, quarantined 2}` | PASS |
| `POST /jobs/search` | UK + US + ambiguous listings | US not stored; ambiguous stored quarantined; UK returned | PASS |
| `POST /jobs/search` | adapter `posted_at` | parsed onto `posted_at` | PASS |
| `GET /analytics/dashboard` | UK + foreign rows | job counts include UK only | PASS |
| `GET /jobs/` | unauthenticated | 401 | PASS (existing auth tests) |
| `GET /jobs/` | another tenant's rows | never returned | PASS (`test_tenant_isolation.py`) |
| Load / stress on production | — | — | NOT RUN — mandate forbids uncontrolled load against production and third-party boards |
| Breakpoint / fuzz of every route | — | — | NOT RUN this pass |
