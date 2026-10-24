# UI interaction matrix — /jobs

Verified in the browser against a local build backed by a scratch copy of the production
corpus (never the production database), plus Vitest + Testing Library.

| ID | Interaction | Expected | Status | Evidence |
|---|---|---|---|---|
| UI-01 | Card header | Employer · City, Country · Posted date (N days ago) or "Posting date unavailable" · arrangement | PASS | browser; `JobSearchPage.location.test.tsx` |
| UI-02 | Drawer header | same facts line | PASS | `JobDrawer` renders `JobFacts` |
| UI-03 | Location chip (Manchester) | request carries `location=Manchester`; chip pressed | PASS | test asserts the request URL |
| UI-04 | "All UK" chip | location param removed | PASS | test |
| UI-05 | Work arrangement chips | `workplace=remote` sent; "Any" removes it | PASS | test |
| UI-06 | Hidden-jobs note | "UK roles only · N outside the UK hidden · M … held back" | PASS | test + browser |
| UI-07 | Pager Next/Previous | server page 2 fetched; resets to 1 on location change | PASS | tests |
| UI-08 | Search button | "Searching…" → "Search" with a result toast | PASS | live: 23.5s, 65 sources |
| UI-09 | Layout 1920 px | rail 300 / results 1092, no overflow | PASS | measured |
| UI-10 | Layout 1440 px | rail 268 / results 854 | PASS | measured |
| UI-11 | Layout 1100 px (sidebar open) | two columns, results 694 | PASS | measured |
| UI-12 | Layout 720 px (= 1440 @ 200% zoom) | stacked, no horizontal scroll | PASS | measured |
| UI-13 | Layout 320 px | sidebar collapsed, stacked, no horizontal scroll | PASS | measured |
| UI-14 | Source labels in rail | ellipsize, never widen the rail | PASS | measured |
| UI-15 | Every other control on every page | — | NOT RUN this pass |
| UI-16 | Keyboard-only walkthrough / screen reader | — | NOT RUN this pass (chips are native buttons with `aria-pressed`; groups labelled) |
