# Defect register

Severity: **P0** data loss / security / false submission · **P1** core promise broken ·
**P2** significant degradation · **P3** polish. Status: FIXED (verified) · OPEN · BLOCKED.

| ID | Sev | Area | Defect | Root cause | Status | Verification |
|---|---|---|---|---|---|---|
| D-001 | P1 | Discovery | 48% of listed jobs were outside the UK (US, DE, CA, IN…) | No country field; global ATS/remote boards stored and listed unfiltered | FIXED | 1,039 prod rows now `uk_eligible=false`; list filters in SQL; 89 classifier tests |
| D-002 | P1 | Discovery | No posting date on any job (0 / 2,143) | `_listing_to_job` dropped the adapter's `posted_at` | FIXED for new/re-discovered jobs | `test_job_service.py` asserts the date reaches the response; existing rows cannot be back-dated without fabricating |
| D-003 | P1 | Jobs UI | City / country not shown; raw postcodes ("M37FB") shown instead | No normalised location | FIXED | `JobFacts` line on card + drawer; `JobSearchPage.location.test.tsx` |
| D-004 | P1 | Jobs UI | Results squeezed into a sliver, rail stretched across the page | Flex `min-width:auto` on the rail | FIXED | Grid with `minmax(0,268px)`; measured 320/720/1100/1440/1920 px, 0 px horizontal overflow |
| D-005 | P1 | Jobs UI | "Searching…" never finished | 30s client timeout < server time; per-row refresh round trips | FIXED | 58s client timeout, 15s fetch deadline, one batched reload; live search 23.5s |
| D-006 | P2 | Jobs UI | Only the first 100 of N stored jobs reachable | Single page fetched | FIXED | Server-side pager; test pages to 2 and resets on filter change |
| D-007 | P2 | Data integrity | Header "2,179 opportunities" vs ~1,000 listable | Dashboard counted all rows | FIXED | `test_dashboard_job_counts_are_uk_eligible_only` |
| D-008 | P2 | Discovery | Duplicates linked by dedup still listed separately | List ignored `canonical_job_id` | FIXED | `TestDuplicatesCollapse` |
| D-009 | P2 | Shell | At 320 px the expanded sidebar left the page 18 px wide | Sidebar never collapsed | FIXED | Auto-collapse ≤900 px; 12 px gutter ≤640 px; measured |
| D-010 | P2 | Jobs UI | "Scoring matches…" cleared early / stuck | One boolean shared by overlapping batches; 100-job request | FIXED | In-flight counter, 25-job batches |
| D-011 | P3 | Filters | Dublin offered as a city filter | Legacy city table | FIXED | Removed; UK cities added |
| D-012 | P2 | Discovery | 302 jobs without a description | LinkedIn guest list cards carry none | OPEN | Enrichment on drawer open works; batch enrichment not built |
| D-013 | P2 | CI | Backend CI fails at `pip install` (`resolution-too-deep`) | Pre-existing dependency resolution | OPEN | Not addressed this pass |
| D-014 | P2 | CI | Docker backend image build fails | Pre-existing | OPEN | Not addressed this pass |
| D-015 | P2 | Data integrity | Dashboard "3 Applied" vs pipeline "0 Applied" | Pipeline counted statuses over the 20 most recent applications; the tile counted all of them server-side | FIXED | Pipeline reads the server's per-status counts; `DashboardPage.test.tsx` (D-015) fails on the old code |
| D-016 | P1 | Automation | Bulk apply / submission state machine cannot run in production | No worker or browser runtime on Vercel serverless | BLOCKED | Needs a long-running worker host; see APPLICATION_AUTOMATION.md |
| D-017 | P3 | Shell | Auto-collapsed sidebar stays collapsed after widening | Collapse persisted, never auto-expanded | OPEN | Header toggle restores it |
