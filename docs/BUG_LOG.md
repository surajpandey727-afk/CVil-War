# AutoApply AI — Bug Log

> ### ⚠️ Correction — 2026-08-12
>
> The "✅ Fixed & verified" markers below were **not** verifiable in this snapshot. When the
> suite was actually run:
>
> * **BUG-001**'s regression test (`authBootstrap.test.tsx`) **failed**. The single-flight fix
>   itself was present and correct in `services/api.ts`; the test could never reach it, because
>   `clear()` in `beforeEach` also clears the session hint that BUG-005's fix uses to gate the
>   boot probe. BUG-005 silently disarmed BUG-001's test.
> * **BUG-002**'s component, `components/auth/PublicOnly.tsx`, **did not exist** — so its test
>   suite could not even load, and `npm run build` failed outright. The whole frontend was
>   unbuildable.
> * **BUG-005**'s claimed test ("skips the probe … no session hint") **was not in the file**.
>
> All of the above are now genuinely fixed and verified — see the 2026-08-12 section at the
> bottom. The lesson for this log: a "fixed" entry is only meaningful if the suite is green at
> the time of writing. Record the command and its output, not the intent.
>
> Full verified state of the repository: [PHASE0_AUDIT.md](PHASE0_AUDIT.md).

Living log of bugs found during testing. The four **P1/P2** items below were found in the
2026-07-10 live end-to-end pass (Playwright driving the real SPA + Vite proxy + live FastAPI +
Redis + a fresh Alembic-migrated DB) and have already been **fixed with TDD** (kept here as a
record). The **deferred** items are minor and intentionally left for a later cleanup pass.

Legend: ✅ Fixed & verified · 🔵 Open (deferred) · Sev: P1 critical · P2 major · P3 minor · P4 polish

---

## Fixed this pass

### BUG-001 — ✅ P1 — Logged out on every hard refresh (and multi-tab)
- **Symptom:** any hard reload of an authenticated page bounced the user to `/login`.
- **Root cause:** `AuthProvider` boot effect called `authService.refresh()` directly, bypassing the
  single-flight guard in `services/api.ts`. React StrictMode's dev double-invoke (and multiple tabs
  in prod) fired two concurrent `POST /auth/refresh`; the backend rotates the refresh token and its
  reuse-detection **revokes the whole token family** on the second call → session cleared.
- **Evidence:** network trace on reload = `refresh 200` immediately followed by `refresh 401`.
- **Fix:** exported `refreshAccessToken` from `services/api.ts`; `AuthProvider` now uses the shared
  single-flight so concurrent boots collapse to one refresh. Test: `__tests__/auth/authBootstrap.test.tsx`.

### BUG-002 — ✅ P2 — New users skipped onboarding
- **Symptom:** after registering, users landed on `/dashboard`, never seeing the onboarding wizard.
- **Root cause:** `PublicOnly` hard-redirected any authenticated user to `/dashboard`, racing/
  overriding `RegisterPage`'s `navigate('/onboarding')`.
- **Fix:** `PublicOnly` gained a `redirectTo` prop (default `/dashboard`); the register route uses
  `redirectTo="/onboarding"`. Test: `__tests__/auth/publicOnly.test.tsx`.

### BUG-003 — ✅ P2 — ATS scores shown as "0"/"1" and always colored red
- **Symptom:** every ATS score on Dashboard / Applications / App-detail / Résumés rendered as `0`
  or `1` and used the "rejected" (red) color band.
- **Root cause:** the API/DB store ATS on a **0–1 scale**, but those views rendered a bare
  `Math.round(score)` and passed it to `atsColor` (whose bands are 85/75/65 = 0–100). `JobSearchPage`
  and `SettingsPage` already multiplied by 100; the others did not. Masked in tests because fixtures
  used 0–100 values and never asserted the rendered number.
- **Fix:** added `atsPercent(score) = Math.round((score ?? 0) * 100)` in `lib/status.ts`, used at all
  display sites; corrected the test fixtures to 0–1. Test: `__tests__/lib/status.test.ts` +
  `ApplicationsPage.test.tsx`.
- **Convention (important):** all ATS / match scores are **0–1 in the API → multiply by 100 to display.**

### BUG-004 — ✅ P2 — App-detail page showed "Untitled role / —"
- **Symptom:** the application detail screen showed "Untitled role" and no company.
- **Root cause:** `GET /applications/{id}` returned `job_title`/`company` = null — only the list
  endpoint eager-loaded the `job` relation and hydrated them.
- **Fix:** `get_application` now `selectinload(Application.job)`; new shared `application_to_response()`
  helper (defensive — hydrates only when `.job` is loaded) used by list/get/create/approve/update.
  Test: `tests/integration/test_applications_api.py::...includes_job_title_and_company`.

---

## Fixed 2026-07-17 (were deferred nits — now all closed, TDD)

### BUG-005 — ✅ P4 — `GET /auth/refresh 401` logs to console on public pages
- **Fix:** added a non-sensitive `aa_session_hint` localStorage marker (set on `setAuth`, cleared on
  `clear`). `AuthProvider` now skips the boot refresh probe entirely when the hint is absent (a
  first-time / logged-out visitor), so no guaranteed 401 fires. A returning device still probes once.
  Test: `__tests__/auth/authBootstrap.test.tsx` ("skips the probe … no session hint").

### BUG-006 — ✅ P4 — Dashboard greeting pluralization: "1 roles"
- **Fix:** `DashboardPage` greeting now renders `role`/`roles` based on `applications_applied === 1`.
  Test: `__tests__/pages/DashboardPage.test.tsx` (greeting pluralization).

### BUG-007 — ✅ P4 — `/admin` header breadcrumb shows "AutoApply AI"
- **Fix:** added `'/admin': 'System health'` to the `CRUMB` map in `components/layout/Header.tsx`.
  Test: `__tests__/components/Header.test.tsx`.

### BUG-008 — ✅ P3 — Job search empty-state copy after a zero-result search
- **Fix:** `JobSearchPage` now branches on `search.isSuccess` — a completed search that matched
  nothing shows "No matching roles / …try broadening…", distinct from the pre-search "No jobs yet".
  Test: `__tests__/pages/JobSearchPage.test.tsx` (distinguishes the two empty states).

---

## Design-parity gaps vs `AutoApply AI.dc.html` (2026-07-13 audit)

Audited the frontend against all 24 sections of the design. The 12 product screens + command
palette + intervention modal + toasts + update-status dialog are all built. Newly added this pass
(ported faithfully, TDD): **404/403/500 system states** (`SystemStatePage` — 404 catch-all, 403 via
`RequireSuperuser` on `/admin`), **offline banner** (`OfflineBanner`, global), and the **"Reset your
password" screen** (`ForgotPasswordPage` at `/forgot-password`, linked from login — shipped as the
design's disabled "COMING SOON" stub). Remaining gaps, all **blocked on the un-built live-browser
backend spike**, not on frontend work:

### GAP-001 — 🔵 P3 — Live Apply "cockpit" view (design §LIVE APPLY COCKPIT)
- The design has a dedicated full cockpit: a live browser **viewport** streaming the agent's screen +
  a step ticker. We have the pieces it needs (dashboard live-now card, app-detail `RunTimeline`,
  intervention modal) but not the combined cockpit, because it renders **live browser screenshots**
  that only exist once `run_apply` streams them (the headful real-browser spike is still pending —
  see the phase-3 memory). Build the cockpit shell when that lands.

### GAP-002 — 🔵 P4 — Screenshot lightbox (design §SCREENSHOT LIGHTBOX)
- A fullscreen viewer for `Application.browser_screenshots`. Same dependency as GAP-001 — no
  screenshots are produced until the live-apply worker runs.

### GAP-003 — ✅ DONE (2026-07-13) — Job detail slide-in drawer (design §JOB DRAWER)
- Built `components/jobs/JobDrawer.tsx`: right-side drawer with match-score ring + skill/keyword
  sub-score bars, missing keywords, suggestions, description, "View posting", and **"Generate
  tailored résumé"**. Clicking a job title on `JobSearchPage` opens it and runs analyze. This also
  **wired the previously-orphaned `useGenerateResume`** action (résumé generate/tailor mount). TDD:
  `__tests__/components/JobDrawer.test.tsx` + a JobSearchPage integration test.

### GAP-005 — ✅ DONE (2026-07-13) — Résumé screen deeper parity (design §RÉSUMÉS)
- Rebuilt `ResumesPage` to the master-detail design: `ResumeCard` (thumbnail, base/tailored/optimized
  **type badges**, target-job subtitle, ATS, optimize + **authenticated-blob Download**) + upload
  dropzone + sticky `ResumePreviewPanel` (ATS ring + skill/keyword/experience/education sub-scores +
  **"Score vs job"** wiring `useScoreResume` with a job picker + PDF/DOCX download) + header
  **"Generate tailored"**. New `resumeService.downloadResumeFile` (bearer blob → object URL).
  TDD: 22 résumé tests. **Live-verified** (login → /resumes → select job → Score → real backend
  breakdown + success toast).
- **Adversarial multi-lens review** (5 lenses × find→verify workflow) found & I fixed: a **HIGH**
  correctness bug (a stale score bled onto the wrong résumé after the selection implicitly shifted —
  fixed with a `score.resume_id === resume.id` guard in the panel), card download hardcoding PDF
  (now picks an available format + disables when none), card subtitle showing template instead of the
  target job, name-scoped a11y labels on the optimize/download buttons + a labeled score-ring, the
  header subtitle copy, and added error/empty/stale-score test coverage.
- **Residual (deferred):** the design's **before/after ATS delta pill** needs a "previous score"
  the backend doesn't expose yet (Resume/ResumeScoreResponse carry no prior value) — blocked like the
  other backend-data gaps. Two low a11y nits left: the disabled "Generate tailored" reason lives only
  in `title` (kept native `disabled`), and the select-card button's aria-label doesn't fold in the
  type/template. `useScoreResume` is now wired (was orphaned).

### GAP-004 — ✅ DONE (2026-07-17) — Password-reset backend + wired frontend
- **Backend:** new `password_reset_tokens` table (migration `0006`), single-use hashed tokens, a
  pluggable **mailer** (`services/mailer.py` — `log` provider by default so it works in dev/CI with
  no mail server; `smtp` provider for real delivery), and endpoints `POST /auth/forgot-password`
  (uniform response → no account enumeration, also closes review item **L4**) + `POST
  /auth/reset-password` (redeem token → set password → revoke all refresh sessions). Service:
  `services/password_reset.py`. Tests: `tests/integration/test_password_reset.py`,
  `tests/unit/test_password_reset_service.py`, `tests/unit/test_mailer.py`.
- **Frontend:** `ForgotPasswordPage` rebuilt into a working form (submit → uniform "check your email"
  confirmation via the shared `AuthNotice` card); new `ResetPasswordPage` at `/reset-password?token=`
  (new + confirm password → success → sign-in link). `authService.forgotPassword/resetPassword`
  added; `api.ts` `isAuthEntry` now covers forgot/reset so their 401s don't trigger a refresh-retry.
  Tests: `__tests__/pages/ForgotPasswordPage.test.tsx`, `__tests__/pages/ResetPasswordPage.test.tsx`.
- **Left to you:** set `EMAIL__PROVIDER=smtp` + SMTP creds (see SETUP_AND_BREADCRUMBS) for real email
  delivery. Email *verification* on register is still deferred (separate product feature).

### GAP-006 — ✅ Backend DONE (2026-07-17) — Platform session import (assisted-login backbone)
- **What:** `run_apply` requires a saved platform session at prerequisite-check time, but there was
  **no write path** to create one. Added `POST/GET/DELETE /api/v1/platform-sessions`: import a captured
  Playwright `storage_state` (encrypted at rest via `CredentialStore` → `user_credentials`
  kind=`platform_cookies`), upsert the `platform_sessions` metadata row, list connected platforms
  (cookies never returned), and disconnect. Service: `services/platform_session.py`; schema validates
  the platform against `SUPPORTED_PLATFORMS` and requires a non-empty `cookies` list. Tests:
  `tests/integration/test_platform_sessions.py`.
- **Why it matters:** a technically-capable user (or the eventual headful assisted-login UX) can now
  provide a session so `run_apply` can proceed — this is the stable contract both capture paths write to.
- **Deliberately NOT built (needs your decision):** the user-facing "Connect LinkedIn/Indeed" UI + the
  headful in-browser capture flow, because that bakes in the automation/ToS posture that is yours to
  decide (SETUP_AND_BREADCRUMBS §4.1). The live capture + real run still need a headful browser host.

Not ported by design intent: **Style guide** (design-reference only) and **Roadmap** (the design
itself labels it "unbuilt").

---

## Fixed 2026-08-12 (Phase 0.5 — build + security repair)

Every entry here was verified by running the command shown. Before: backend `653 passed,
6 failed`; frontend `118 passed, 3 failed, 1 suite unloadable`; `npm run build` **failing**.
After: backend `661 passed, 0 failed, 2 skipped, 1 xfailed`; frontend `124 passed, 0 failed`;
`npm run build` **passing**; `ruff check app/` and `npm run lint` clean.

### BUG-010 — ✅ P1 — The frontend did not build
- **Symptom:** `tsc` and `npm run build` failed with
  `TS2307: Cannot find module '@/components/auth/PublicOnly'`.
- **Root cause:** `App.tsx` (4 routes) and `publicOnly.test.tsx` imported a component that was
  not in the repository. BUG-002 above describes fixing it; the file itself was absent.
- **Fix:** added `components/auth/PublicOnly.tsx`, honouring the `redirectTo` contract its test
  already specified. It only branches on `authenticated`, because `AuthProvider` renders a
  spinner instead of the router until auth settles, so a route guard never sees `loading`.

### BUG-011 — ✅ P2 — Password reset was a dead link end-to-end
- **Symptom:** the emailed reset link 404'd.
- **Root cause:** `mailer.build_reset_link` sends users to
  `{frontend_base_url}/reset-password?token=…`, and `ResetPasswordPage.tsx` existed with tests —
  but **no route was ever mounted** in `App.tsx`.
- **Fix:** registered `/reset-password` inside `PublicOnly`.

### BUG-012 — ✅ P1 (security) — PII gate failed open
- **Symptom:** `pii_clean("Applicant John Smith should click apply")` returned `True` (clean).
- **Root cause:** `_contains_person_name` caught every exception from `get_nlp()` and returned
  `False`. Name detection needs spaCy's `en_core_web_sm`, which **only the Dockerfile installs**
  — so on any pip-installed checkout the gate silently passed everything. DomainSkills are
  shared across tenants and injected into later agent prompts, so this is a cross-tenant leak
  path, not a cosmetic issue. The docstring claimed a regex fallback; the regexes match
  emails/phones/keys/addresses and nothing name-shaped.
- **Fix:** fail closed (assume PII when the model is unavailable) and log an error naming the
  install command. Test: `test_gate_fails_closed_when_the_ner_model_is_unavailable`.

### BUG-013 — ✅ P2 — …and rejected its own best input once the model WAS present
- **Symptom:** found immediately after fixing BUG-012 by installing the model — four previously
  green tests went red.
- **Root cause:** spaCy tags **"Easy Apply"** as a `PERSON` entity. In Docker (where the model
  exists) the gate therefore discarded exactly the guidance the self-evolving harness exists to
  accumulate, e.g. *"Easy Apply lives at .jobs-apply-button"*. The local suite passed only
  because no model was installed and the gate was failing open — the two bugs concealed each
  other.
- **Fix:** exact-match (case-folded) allow-list of job-board UI phrases in `_NON_NAME_TERMS`,
  applied to whole entity spans so real names are unaffected. Test:
  `test_job_board_ui_phrases_are_not_treated_as_names`, which also asserts
  `"Contact Sarah Bennett to resume"` is still rejected.

### BUG-014 — ✅ P2 — Four upload tests failed on Windows `MAX_PATH`
- **Symptom:** `FileNotFoundError` raised from inside a thread-pool executor, which looked like
  a missing-`mkdir` bug in `LocalFileStorage.put` (it does create parents — `local.py:33`).
- **Root cause:** the storage root defaults to `./data/storage` relative to CWD, so tests wrote
  into the working tree. Repo root (170 chars) + `users/<32>/uploads/<32>.pdf` = **275 chars**,
  over Windows' 260-char limit.
- **Fix:** session-scoped autouse fixture pointing `STORAGE__LOCAL_ROOT` at a temp dir. Uses the
  **env var**, not the cached `Settings` object, because `test_migrations` clears that
  `lru_cache` and an in-place mutation is lost on rebuild. Also stops the suite mutating the
  working tree.

### BUG-015 — 🔵 P1 — Job discovery is completely non-functional (**open**)
- **Symptom:** `POST /jobs/search` returns `total: 0` for every query.
- **Root cause:** `core/automation/agent.py` imports `BrowserConfig`, removed in modern
  browser-use; `pyproject` had no upper bound so pip installs 0.11.13. All three platform
  plugins raise, and `services/job_search.py` swallows per-platform failures — so total
  subsystem failure is indistinguishable from "no jobs matched".
- **Partial fix:** the error message no longer claims the package is missing (it is installed).
- **Still open:** deliberately not repaired by porting the scrapers, since PHASE0_AUDIT §5.3
  recommends official job APIs as the primary discovery path. Tracked as B14.

### BUG-016 — ✅ P2 — `docker compose up` started against an empty database
- **Root cause:** `docker-compose.yml` had no migration step (only the prod compose did), and
  **no Dockerfile copied `backend/alembic.ini`** — so even the documented production release
  command `run --rm api alembic upgrade head` could not locate the migration scripts.
- **Fix:** added a one-shot `migrate` service that `backend` and `worker` gate on via
  `service_completed_successfully`, and copied `alembic.ini` into the backend and api images.
- **Not verified end-to-end:** Docker is not installed on this machine.

### BUG-017 — ✅ P2 — `pip install -e ".[dev]"` failed on a clean machine
- **Root cause:** resolving `langchain-*` made pip backtrack through litellm releases to
  1.93.0, which ships only an sdist whose metadata build requires a Rust toolchain.
- **Fix:** pinned `litellm>=1.96,<2`, and removed seven never-imported dependencies
  (`sentence-transformers`, `faiss-cpu`, `scikit-learn`, `numpy`, `fuzzywuzzy`,
  `python-Levenshtein`, `python-dateutil`) — `sentence-transformers` alone pulls PyTorch.
