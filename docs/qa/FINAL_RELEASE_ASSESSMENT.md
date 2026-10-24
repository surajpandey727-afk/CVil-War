# Release assessment — 2026-10-24

## Verdict

**The UK-only jobs release is shippable; the full 16-phase mandate is not complete.** The
defects reported from the /jobs screenshot are fixed and verified, and the production data
has been migrated and backfilled. Several gates in the mandate cannot honestly be marked PASS
yet — they are listed below with the reason, not rounded up.

## Release gates

| Gate | Status | Evidence / reason |
|---|---|---|
| 100% of displayed jobs have verified UK eligibility | PASS | list query filters `uk_eligible`; 1,014 / 2,143 prod rows eligible; 1,129 hidden (1,039 non-UK, 90 quarantined); no deletions |
| Every actionable job has a verified location and an application link | PASS | listed rows are `verified` by construction; all 2,143 rows carry an http(s) `url` |
| Posting date shown, or "Posting date unavailable" — never fabricated | PASS | `posted_at` from source only; card/drawer state unknowns |
| 100% critical interactions pass | FAIL (partial) | /jobs critical path PASS (UI-01…UI-14); other pages NOT RUN this pass |
| Zero duplicate submissions | BLOCKED | no automation worker in production (D-016); vacancy-level dedup added (D-008) |
| 100% SUBMITTED backed by evidence | BLOCKED | same |
| Interruption recovery | BLOCKED | same |
| Zero open P0/P1 | FAIL | D-016 (automation cannot run on Vercel) is P1 and needs a hosting decision |
| CI green | FAIL | frontend green; backend install `resolution-too-deep` (D-013) and Docker build (D-014) pre-existing, not fixed this pass |

## Production changes made (all additive, reversible)

1. Alembic `a3d9c51e7b20 → e5b2c8d41f07`: ten nullable/defaulted columns + two indexes on
   `jobs`. Downgrade drops them; raw `location` untouched.
2. Backfill: derived location fields written for 2,143 rows; re-run reports 0 changes.
3. JSON backup of the `jobs` table taken before either step (kept outside the repo).

## Not done this pass (carried forward)

Phase 4 (React Bits LatticeLoader — the requested `npx shadcn add` needs Tailwind + shadcn,
which conflicts with the project rule "no component library; extend the hand-rolled design
system"; needs the owner's call), Phases 5/9/11/12 beyond the jobs surface, CI repairs (D-013/D-014), batch description enrichment
(D-012).
