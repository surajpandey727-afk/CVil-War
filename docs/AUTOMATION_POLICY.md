# CVil-War Automation Policy

**Owner:** Suraj Pandey · **Version:** 1.0 · **Status:** enforced in code

This is the policy the auto-apply agent operates under. It is not a statement of intent —
every clause below maps to a rule in `backend/app/core/policy/rules.py`, is evaluated before
any submission, and the decision is written to the application timeline with the id of the
rule that produced it. A clause with no rule behind it does not belong in this document.

Read this alongside the enforcement code. If the two disagree, the code is the bug.

---

## 0. Scope and intent

The system applies for jobs on the operator's behalf. That means it acts as the operator to
third parties who did not agree to talk to a machine. The whole policy follows from taking
that seriously.

**The optimisation target is interview probability, not application count.** Almost every
volume control below would be "wrong" if the goal were throughput. It is not. A hundred
generic applications is a worse outcome than ten considered ones, and it is also the
behaviour most likely to get an account flagged.

### Decision vocabulary

Four verdicts, deliberately distinguished, because collapsing them is how automation ends up
either spamming or silently dropping work:

| Verdict | Meaning | What happens |
|---|---|---|
| `ALLOW` | Nothing objects. | Submit. |
| `HOLD` | Not now, but plausibly later. | Stays queued, retried when the condition clears. Never a dead end. |
| `ESCALATE` | A human must decide. | Enters the action queue with the reason. Never auto-resolved. |
| `BLOCK` | Never, for this application. | Terminal, with the rule recorded. |

`HOLD` vs `BLOCK` is the load-bearing distinction. Outside the run window is a `HOLD`; a
blocked employer is a `BLOCK`. An engine that only had "no" would either lose the job or
retry it forever.

**The engine fails closed.** A rule that cannot evaluate — missing data, an exception —
returns `ESCALATE`, not `ALLOW`. Unknown state is not consent. This is the same principle
applied to the PII gate after it was found failing open (see `PHASE0_AUDIT.md`).

---

## 1. Truthfulness and integrity — non-negotiable

These are not settings. They have no toggle in the UI and no field in the stored policy; they
are shown so the operator can see what the system will not do, and they are enforced whatever
the rest of the configuration says.

**1.1 No fabricated experience.** The agent may reorder, re-weight, re-word and re-frame what
is in the operator's CV repository. It may not invent an employer, a date, a title, a
qualification, a certification or a metric. Concretely: rewriting "led delivery" as "owned
end-to-end delivery of a £2m programme" is a fabrication unless the £2m is in the source
material. Tailoring operates at levels 0–4 of the fabrication ladder; level 5 (invention) is
blocked at the generator, not filtered afterwards.

*Rule:* `integrity.no_fabrication` — locked on.

**1.2 Eligibility questions are never auto-answered.** Right to work, visa status,
sponsorship requirement, security clearance, protected characteristics, disability, criminal
record, notice period and salary expectation are answered by the operator or not at all. A
wrong answer to any of these is a misrepresentation to an employer and, for several, a legal
matter. Encountering one escalates.

*Rule:* `integrity.no_auto_eligibility_answers` — locked on.

**1.3 No bot-protection circumvention.** CAPTCHAs, device checks and rate-limit challenges
are respected as the access decisions they are. The agent does not solve, farm out, or evade
them; it stops and asks the operator to take the session. Nor does it rotate credentials or
identities to get around a limit — that is the same evasion with extra steps.

*Rule:* `integrity.no_bot_circumvention` — locked on.

**1.4 One identity.** Applications go out under the operator's real name and real contact
details. No aliases, no throwaway identities, no applying on behalf of anyone else.

*Rule:* `integrity.single_identity` — locked on.

**1.5 Disclosure is available, not mandatory.** Whether to tell an employer the application
was AI-assisted is the operator's call and defaults to off, because no jurisdiction requires
it and most employers do not ask. Where an employer *does* ask, 1.2 applies: the question is
escalated and answered honestly.

*Rule:* `integrity.disclose_ai_assistance` — operator-configurable, default off.

---

## 2. Volume and rate

Every limit here exists twice over: it protects the employer's inbox from being treated as a
firehose, and it protects the operator from the account suspension that reliably follows.

**2.1 Daily cap.** Default **20** submissions per day. This is well above a considered human
pace and well below anything a portal would read as scripted.

**2.2 Hourly cap.** Default **5**. The daily cap alone permits twenty applications in four
minutes, which no human does.

**2.3 Minimum spacing.** Default **90 seconds** between submissions. Uniform sub-second
timing is the single clearest bot signature in a portal's logs.

**2.4 Per-employer cap.** Default **2** applications to the same company per rolling 7 days.
Six applications to one employer in a week does not read as enthusiasm.

All four are `HOLD`, never `BLOCK` — the work stays queued and goes out when the window
opens.

*Rules:* `volume.daily_cap`, `volume.hourly_cap`, `volume.min_spacing`,
`volume.per_company_week`.

---

## 3. Duplicate suppression

**3.1 Never twice to the same posting.** A hard invariant, not a preference. Duplicate
submissions are the most visible possible automation failure and the fastest route to being
ignored by a recruiter.

*Rule:* `duplicates.same_posting` — locked on, `BLOCK`.

**3.2 Re-application cooldown.** Default **90 days** before re-applying to a materially
similar role at the same employer. Below the cooldown the application is held, not dropped,
because the cooldown does expire.

*Rule:* `duplicates.reapply_cooldown` — `HOLD`.

---

## 4. Human oversight

**4.1 Apply mode.** `review` (default), `batch` or `autonomous`. This is the master control:
in `review`, nothing leaves without an explicit approval.

**4.2 Kill switch.** A single toggle that stops all submission immediately. Everything queued
stays queued. This exists because "how do I make it stop right now" must have an answer that
is not "kill the worker".

*Rule:* `oversight.kill_switch` — `HOLD`.

**4.3 High-stakes review.** Applications above a salary threshold (default **£120k**) always
get a human look regardless of apply mode. The cost of a bad automated application scales
with the role.

*Rule:* `oversight.high_value_review` — `ESCALATE`.

**4.4 First run on a new portal.** The first application through any portal is reviewed by a
human, whatever the mode. Portal form-filling is the least reliable part of the system and
the first submission is where an unseen field shows up.

*Rule:* `oversight.new_portal_first_run` — `ESCALATE`.

**4.5 Pause on challenge.** Any CAPTCHA, MFA prompt or identity check hands the session to
the operator. Follows from 1.3.

*Rule:* `oversight.pause_on_challenge` — `ESCALATE`.

---

## 5. Match and eligibility

The system does not apply to roles it cannot argue for. This is the interview-probability
target expressed as a filter.

**5.1 Minimum ATS match.** Default **75%**. Below it, the posting is kept, scored and shown —
it is simply not auto-applied to.

**5.2 Salary floor**, **5.3 seniority band**, **5.4 blocked employers** — operator-defined.
Blocked employers `BLOCK`; the other two `HOLD`, since a posting can be re-evaluated when the
policy changes.

An unscoreable posting (no CV text, scorer unavailable) does not silently pass the gate. It
escalates — see §0 on failing closed.

*Rules:* `match.min_ats_score`, `match.salary_floor`, `match.seniority`,
`match.blocked_employer`.

---

## 6. Run window

Submissions land inside working hours in the operator's timezone (default Mon–Fri,
08:00–19:00 Europe/London). Two reasons: a 03:00 application timestamp is a tell, and it
means the operator is awake to handle anything that escalates.

Outside the window everything queues. Nothing is lost.

*Rule:* `window.run_window` — `HOLD`.

---

## 7. Failure handling

**7.1 Retries** are bounded (default 3) and backed off, and apply only to failures classified
as transient. A form that rejected the submission is not retried — retrying it just submits
the same wrong thing again.

**7.2 Circuit breaker.** After **3** consecutive failures on one portal, that portal is
suspended and the operator is told. Continuing to hammer a broken integration produces
nothing but noise in someone else's logs.

*Rule:* `failure.circuit_breaker` — `HOLD`.

**7.3 Email fallback** is opt-in and only ever used where the posting itself publishes an
application address.

**7.4 Retries never widen scope.** A retry re-attempts the same application on the same
portal. It does not fall back to a different account, a different identity, or a different
route that the policy would otherwise have blocked.

---

## 8. Data protection

**8.1 Credentials.** Portal credentials are encrypted at rest, never logged, never sent to an
LLM, and never included in a trajectory or error report.

**8.2 Personal data in logs.** Names, addresses, phone numbers and email addresses are
redacted from logs and LLM prompts by the PII gate. Locked on.

*Rule:* `privacy.redact_pii` — locked on.

**8.3 Retention.** Generated CVs and cover letters are kept for a configurable period
(default: indefinitely, since they are the operator's own documents) and are deleted with the
account.

**8.4 Third parties.** Under the zero-cost constraint the system uses only free, public
endpoints. Operator data is not sold, shared, or sent anywhere except the job portal being
applied to and the configured LLM endpoint.

---

## 9. Auditability

Every policy decision — including every `ALLOW` — is written to the application timeline with
the rule id, the verdict and the human-readable reason. The operator can always answer "why
did it apply to that?" and "why hasn't it applied to this?" without reading logs.

An automated system that cannot explain a decision after the fact is not auditable, and an
unauditable system is one you cannot safely leave running.

---

## 10. Changing this policy

The stored policy is versioned. Changes take effect on the **next** run, never on one in
flight — a threshold dragged across a value mid-run would otherwise change the rules under a
submission already being made.

Clauses marked *locked* have no override. They are not configuration; they are the conditions
under which the operator is willing to let software act as them.
