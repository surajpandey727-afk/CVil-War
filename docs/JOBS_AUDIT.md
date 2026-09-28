# Jobs section — audit, fixes and evidence

Date: 2026-09-28

Scope: the Jobs discovery surface — source selection, filtering, job cards, search history,
and the shape of the job data all of them read.

---

## 1. What was broken

### 1.1 The salary filter read the wrong number out of most postings

`salaryK()` in `frontend/src/pages/JobSearchPage.tsx` took the smallest number anywhere in the
salary string. Against real UK salary lines:

| Posting says | Filter read it as |
|---|---|
| `Up to £60,000 + 10% bonus` | £10k |
| `£65,000 per annum, 25 days holiday` | £25k |
| `£500 per day` | £500k |
| `£1,200/day outside IR35` | £1.2k |
| `$120,000 - $150,000` | £120k |

**Root cause.** Free-text salary was parsed by a four-line heuristic with no notion of
context, period or currency. A bonus percentage, a holiday allowance and a day rate are all
"the smallest number in the string".

**Consequence.** A minimum-£50k search hid a £60k role and kept a £25k one. The card showed
the posting's own text, so the card and the filter behind it disagreed with nothing on screen
to explain it. Sorting by salary was wrong for the same reason.

### 1.2 The sources rail was static and truncated

It rendered `SOURCE_TIERS` / `sourcesInTier()` from the static catalogue in `lib/sources.ts`.
`useSources()` fetched the live registry but only its `live_keys` were used. Each tier was then
cut with `.slice(0, 6)`.

**Consequence.** Of 69 career-page sources, six were reachable; the other 63 could neither be
seen nor toggled. Sources with no adapter, and ones disabled in Settings, were listed inline
with a "SOON" tag — so most of what was on screen could not return a result.

### 1.3 There was no sponsorship filter

`sponsor_confidence` existed end to end and appeared on the card, but only when it was *not*
`unknown`, and nothing filtered on it. For a candidate who needs a Skilled Worker visa this is
the first filter they would reach for.

### 1.4 There was no search history

A grep for `recentSearch|searchHistory|Recently` across the frontend returned nothing. The
feature did not exist. The static thing on screen was the Role-targets chip rail, which is the
candidate's own profile and a different control.

### 1.5 No canonical job model

`salary_min/max/currency` and `sponsorship_status` did not exist on the API or the TypeScript
type. Every consumer derived them independently, which is why 1.1 could produce a card and a
filter that disagreed about the same posting.

### 1.6 The test mock did not match the API

`__tests__/mocks/handlers.ts` returned source tiers keyed `label`; the endpoint
(`SourceTierResponse` in `backend/app/api/v1/sources.py`) sends `name`. Nothing caught it
because nothing read a tier's name until the rail started rendering the live catalogue.

### 1.7 Two tests were passing vacuously

`findByRole('button', { name: 'Sponsors' })` matched the new sponsorship *filter chip* rather
than the job row, so the assertion that followed ran before any job had rendered — "the
excluded role is absent" passed because nothing was there yet.

---

## 2. What changed

### Backend — one parser, served as data

- **`app/core/salary.py`** (new). Reads a published salary line into an annualised band:
  strips fragments whose numbers are not pay (percentages, holiday allowances, IR35, visa
  tiers), detects currency and period, annualises day (×220 billable days), hourly (×1650) and
  monthly (×12) rates, and rejects figures outside a credible range. Returns an empty band —
  never `0` — when nothing is recoverable.
- **`app/schemas/job.py`**. `JobListingResponse` now derives and serves `salary_min`,
  `salary_max`, `salary_currency`, `salary_period`, `salary_annualised` and
  `sponsorship_status`. `sponsorship_status()` collapses the five evidence grades into the
  three answers a candidate filters by: `available`, `not_specified`, `none`.

`salary_range` and `sponsor_confidence` are unchanged and still served — the derived fields sit
beside the employer's own words, they do not replace them.

No migration: both fields are derived at serialisation time from columns that already exist.

### Frontend — one reading, shared by the filter and the card

- **`lib/jobModel.ts`** (new). `salaryBand()`, `sponsorshipStatus()`, the bracket definitions,
  overlap matching and `formatSalary()`. It reads the served fields; it does not re-parse. A
  second parser in a second language is exactly how `lib/sources.ts` drifted from the backend
  registry.
- **`lib/jobFilter.ts`** (new). The filter pass, lifted out of the page so it can be exercised
  directly rather than through a mount and a network round trip.
- **`store/useDiscoveryStore.ts`**. `minSalaryK` replaced by `salaryBrackets` +
  `salaryCustomMinK/MaxK`; `sponsorship` added; `recentSearches` added with dedupe,
  move-to-top, a cap of 10 and persistence. Migration to v3 carries a slider the operator had
  actually set over to the custom floor, and an untouched `0` to `null` rather than an active
  £0 floor.
- **`pages/JobSearchPage.tsx`**. Sources rail now renders the live registry, shows only what
  can return results, and links the rest to Manage with a count. Salary brackets, a custom
  window and sponsorship chips added. Card salary and sponsorship read the canonical fields.
  Sponsorship now shows on every card, including "Not stated". A note appears when the page
  holds fewer roles than the server stores.
- **`components/jobs/JobDrawer.tsx`**. Shows the annualised equivalent beside a day or hourly
  rate, so the drawer cannot contradict the card.

### Salary brackets

£20–30k, £30–40k, £40–50k, £50–60k, £60–75k, £75k+, plus a custom min/max in thousands.
Selection is an OR. Matching is **overlap**, not containment: a role advertised at £55–85k is a
genuine candidate for a "£60–75k" search, and requiring containment would drop exactly the
wide, well-paid ranges worth seeing.

**A role that publishes no salary is never hidden by a salary window.** Most UK postings
publish nothing; treating them as £0 would remove the majority of the market. "Published salary
only" is the separate control for that, and the panel says so in words.

### Source visibility

The rail shows a source when the live registry lists it in `live_keys` **and** Settings has not
switched it off. Everything else is counted and linked to Manage. An empty selection means
"every source", so every rail row reads as on until the operator narrows it; switching the
first one off writes the implied list down, and re-selecting everything collapses back to the
empty list so sources added to the registry later are not silently excluded.

---

## 3. Test results

| Level | What | Result |
|---|---|---|
| Unit (backend) | `test_salary_parsing.py` — 26 cases, including every regression in §1.1 | 26 passed |
| Unit (backend) | `test_job_canonical_fields.py` — derived fields and the sponsorship mapping | 12 passed |
| Unit (frontend) | `jobModel.test.ts` — bands, brackets, overlap, formatting, sponsorship | 28 passed |
| Unit (frontend) | `jobFilter.test.ts` — every filter rule, sorting, and two performance guards | 16 passed |
| Unit (frontend) | `useDiscoveryStore.test.ts` — history dedupe, cap, restore, persistence, migration | 18 passed |
| Integration (frontend) | `JobSearchPage.discovery.test.tsx` — rail, filters, history, controls | 37 passed |
| Integration (frontend) | `JobSearchPage.test.tsx` — existing list and apply behaviour | 25 passed |
| System (backend) | `test_jobs_api.py::TestCanonicalFieldsOverTheWire` — the fields over real HTTP | 6 passed |
| Regression | every defect in §1 has a named test | covered |
| Performance | filter pass over 5,000 roles, and with 200 selected sources | < 33 ms each |
| Whole suites | backend `tests/unit` + `tests/integration` | 1692 passed, 2 skipped, 1 xfailed |
| Whole suites | frontend `vitest run` | 404 passed, 47 files |
| Build | `npm run build`, `tsc --noEmit`, `eslint`, `ruff` | clean |

The performance guards are deliberately loose (two frames at 60fps). They exist to catch an
accidentally quadratic rule — an `includes` over an array inside the predicate, which is what
the source check used to be — not to benchmark.

---

## 4. Known limitations, stated rather than hidden

- **Filters run over one page.** The list endpoint is fetched at `page=1, size=100`, so filters
  apply to the 100 most recent stored roles, not the whole corpus. The screen now says
  "of N stored" when there are more, with a tooltip explaining it. Server-side filtering and
  pagination would be the real fix and is a larger change than this audit.
- **Currency is reported, not converted.** A `$120,000` role keeps `salary_currency: "USD"` and
  is compared against the brackets on its face value. Converting would need a rate source and a
  date, and inventing one would be worse than saying which currency it is.
- **Field names follow the codebase, not the brief.** The canonical model uses `platform` and
  `posted_date` where the brief said `source` and `date_posted`. Renaming them would churn the
  whole API for no behavioural gain; the shape asked for is present under the established names.
- **Signed-in browser verification was not performed.** The local API in `backend/.env` points
  at the production Supabase instance. Verifying the screen in a browser would have meant
  either creating an account in that database or using the owner's own credentials, and neither
  is something to do unasked. The app was confirmed to boot and route cleanly with no console
  errors; the UI itself is verified by tests that mount the real component and click the real
  controls.
