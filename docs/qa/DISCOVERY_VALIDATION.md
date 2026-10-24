# Discovery validation — UK-only policy

## Policy (backend `app/core/geo/classify.py`)

A job is listed only when its location is **verified** to be in the UK, or it is a remote role
that **explicitly** hires in the UK. Evidence, strongest first:

1. explicit country text in the posting's own location (`United Kingdom`, `USA`, `Remote - Canada`,
   a US state or Canadian province code, an ISO code such as `gb` / `us`);
2. a complete UK postcode (`EC4N6EU`, `M3 7FB`);
3. a known place (UK town/county or foreign city). UK names with a famous foreign namesake
   (`Cambridge`, `Birmingham`, `Richmond`, …) are accepted bare **only** from a UK-scoped source;
4. a UK-scoped source (Reed, Adzuna `/gb/`, MoveJobs, Tarve, UK Visa Jobs) vouching for an
   otherwise unrecognised place name.

Never used as evidence: employer HQ, posting domain, description language or currency.
`Remote`, `Worldwide`, `EMEA`, `Europe` alone → **ambiguous** → quarantined (stored, not listed).
Verified non-UK listings are **not stored** at ingestion; nothing already stored is deleted.

Stored per job: `country_code`, `country_name`, `city`, `region`, `workplace_type`,
`remote_eligible_countries`, `location_verification_status`, `location_evidence_source`,
`location_verified_at`, `uk_eligible`; raw text kept in `location` (`raw_location` in the API).
Dates kept distinct: `posted_at` (source), `discovered_at`, `last_verified_at`, `updated_at`.

## Results on the production corpus (2,143 jobs, 2026-10-24)

| Outcome | Rows | Listed |
|---|---|---|
| Verified UK / UK-eligible remote | 1,014 | yes |
| Verified outside UK | 1,039 | no (kept, `uk_eligible=false`) |
| Ambiguous (macro region, bare namesake) | 50 | no — quarantined |
| Unknown (no usable location) | 40 | no — quarantined |

Backfill: `scripts/reclassify_locations.py` — dry run, apply, re-run reported `changed: 0`
(idempotent). Row count before and after: 2,143 / 2,143.

Manual audit of every distinct location string (660) in the corpus: no foreign location
classified UK; corrections made during the audit — `SF` read as an ISO code, `Homeoffice`
(German) treated as Germany (language is not location evidence), Dublin listed as a UK city
filter.

## Checks

| ID | Check | Status | Evidence |
|---|---|---|---|
| DV-01 | Foreign locations never UK-eligible (25 real strings incl. `SF, NY, SEA`, `US-CA-Menlo Park`, `München`) | PASS | `tests/unit/test_uk_location_policy.py` |
| DV-02 | UK namesakes abroad (`Birmingham, AL`, `London, ON`, `Cambridge, MA`) follow the state/province | PASS | same |
| DV-03 | Bare namesake from a global board quarantined; same from Reed accepted | PASS | same |
| DV-04 | Remote roles eligible only when the UK is named | PASS | same |
| DV-05 | Verified non-UK listing not persisted; ambiguous persisted quarantined | PASS | `test_job_service.py::test_ingestion_enforces_the_uk_only_policy` |
| DV-06 | `/jobs/` lists only UK-eligible; `include_quarantined=true` shows the rest | PASS | `test_jobs_api.py` |
| DV-07 | `/jobs/location-summary` accounts for every stored row | PASS | `test_jobs_api.py` |
| DV-08 | Posting date carried from adapter to `posted_at`; unparseable → null, never guessed | PASS | `test_posted_at_parsing.py`, `test_job_service.py` |
| DV-09 | Existing rows recover a posting date when re-discovered (never overwriting one) | PASS | `job_search._register` (covered by search tests) |
| DV-10 | Linked duplicates listed once; UK duplicate of a quarantined canonical stays visible | PASS | `test_jobs_api.py::TestDuplicatesCollapse` |
| DV-11 | Dashboard / pipeline counts UK-eligible only | PASS | `test_analytics_api.py::test_dashboard_job_counts_are_uk_eligible_only` |
| DV-12 | Live search end-to-end (65 real sources, scratch DB) | PASS | 23.5s, 51 UK roles, 2 non-UK rejected at ingestion |
| DV-13 | Existing 2,143 production rows have a posting date | FAIL | the dates were never stored; they return as each job is re-discovered. Not fabricated. |
| DV-14 | 302 jobs without a description | FAIL (known) | 253 are LinkedIn guest cards whose list endpoint carries no description; the drawer's "fetch full posting" enrichment fills them on open. 64 of the 302 are UK-eligible. Batch enrichment: NOT RUN. |
| DV-15 | Every listed job has an application link | PASS | all 2,143 production rows carry an http(s) `url` (checked against the 2026-10-24 backup) |
