# Application automation, bulk apply, background tasks (Phases 6–8)

## Status: BLOCKED in production

The automation path (`DISCOVERED → … → SUBMITTED`, bulk apply, the Action Required queue,
session resume, background notifications) runs on the arq worker plus a real browser
(`core/automation/runtime/`). The production deployment is two Vercel serverless functions:

* no long-running worker process exists to consume the queue;
* there is no browser runtime, and a 60s `maxDuration` could not hold a form-fill session;
* the mandate requires sandboxed or mocked submission endpoints and forbids real submissions
  during testing, which rules out "testing it live".

Queuing an application from `/jobs` therefore records it (status `queued` / `pending review`)
but nothing advances it in production. That is accurate rather than broken: the UI never
claims a submission, and `SUBMITTED` is never set without evidence. It is still a P1 gap
(D-016) against the product's promise.

## What unblocks it

A host that can run a persistent worker and a headless browser at £0 — for example a
free-tier container on Render, Fly.io or a home machine — pointed at the same Supabase
database and Redis. The worker code exists; what is missing is somewhere to run it. That is a
hosting decision with cost and security implications, so it is the owner's call, not one to
make silently.

## Checks

| ID | Check | Status |
|---|---|---|
| AA-01 | State machine transitions and guards | NOT RUN this pass (existing unit tests in `tests/unit` still pass) |
| AA-02 | Idempotent submission / no duplicate applications | NOT RUN this pass (dedup now collapses one vacancy seen on several boards — D-008 — which removes the most common duplicate-application route) |
| AA-03 | Submission evidence before `SUBMITTED` | NOT RUN this pass |
| AA-04 | Bulk apply as a durable workflow with resume | BLOCKED — no worker in production |
| AA-05 | Action Required queue for CAPTCHA/MFA hand-off | BLOCKED — no browser runtime; CAPTCHA/MFA are never bypassed by design |
| AA-06 | Background notifications | BLOCKED — no worker |
