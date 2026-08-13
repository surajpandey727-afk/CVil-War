"""The rule catalogue — one entry per clause of ``docs/AUTOMATION_POLICY.md``.

This module is the single source of truth for three things that used to drift apart: what the
policy says, what the code enforces, and what the UI offers. A rule carries its own clause
reference, its rationale, its verdict, and the spec for the control that edits it, so:

* ``GET /settings/automation-policy/catalogue`` renders the automation screen from this list —
  add a rule here and the control appears, with no frontend change;
* ``test_policy_catalogue`` asserts every clause in the document has a rule and every rule
  names a real :class:`AutomationPolicy` field.

Rules are pure. They receive a policy and a :class:`PolicyContext` and return a
:class:`Fired` or ``None``; they never touch the database, the clock, or the network. The
clock in particular is passed in as ``ctx.now`` so a run-window test is not a coin flip on
what time CI happens to run.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.policy.model import (
    AutomationPolicy,
    ControlKind,
    ControlSpec,
    PolicyContext,
    Verdict,
)

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SENIORITY_LEVELS = ("Junior", "Mid", "Senior", "Lead", "Principal")


@dataclass(frozen=True)
class Fired:
    """A rule objecting, with the reason shown to the operator verbatim."""

    reason: str
    #: Overrides the rule's default verdict. Used where one rule has two severities — a
    #: challenge escalates when the operator wants the session, and blocks when they do not.
    verdict: Verdict | None = None
    #: When this could clear. Only meaningful for HOLD.
    retry_after: datetime | None = None


class Enforcement(StrEnum):
    """Where a clause is actually enforced.

    Not every clause is a gate. Saying so explicitly stops the catalogue from implying that
    a toggle blocks submissions when it only changes what the agent does.
    """

    #: Checked here, before every submission.
    GATE = "gate"
    #: An invariant enforced at a different layer. Listed for transparency; no toggle.
    ELSEWHERE = "elsewhere"
    #: Changes agent behaviour rather than permitting or refusing a submission.
    BEHAVIOUR = "behaviour"


@dataclass(frozen=True)
class Rule:
    """One policy clause, its control, and its check."""

    id: str
    #: Clause reference into ``docs/AUTOMATION_POLICY.md`` — e.g. ``"§2.1"``.
    clause: str
    title: str
    #: Why the clause exists. Shown in the UI; an operator changing a limit deserves to know
    #: what it was protecting them from.
    rationale: str
    enforcement: Enforcement
    control: ControlSpec
    #: Attribute on :class:`AutomationPolicy` this rule reads. Empty for locked invariants.
    field_name: str = ""
    #: Default verdict when the check fires.
    verdict: Verdict = Verdict.HOLD
    #: Absent for ``ELSEWHERE`` and ``BEHAVIOUR`` rules.
    check: Callable[[AutomationPolicy, PolicyContext], Fired | None] | None = None
    #: Where an ``ELSEWHERE`` invariant actually lives, so the claim is checkable.
    enforced_by: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def locked(self) -> bool:
        """True when the operator cannot change this — the §1 invariants."""
        return self.control.kind is ControlKind.LOCKED


LOCKED = ControlSpec(kind=ControlKind.LOCKED)
TOGGLE = ControlSpec(kind=ControlKind.TOGGLE)


# -- §1 truthfulness and integrity ------------------------------------------------------
# These have no field on AutomationPolicy on purpose. They are the conditions under which the
# operator is willing to let software act as them, not preferences, so there is nothing to
# store and nothing to switch off.


def _no_auto_eligibility(_p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if not ctx.eligibility_questions:
        return None
    listed = ", ".join(ctx.eligibility_questions[:3])
    more = f" (+{len(ctx.eligibility_questions) - 3} more)" if (
        len(ctx.eligibility_questions) > 3
    ) else ""
    return Fired(
        f"The form asks questions only you may answer: {listed}{more}. "
        "Answer them and the application will continue."
    )


def _pause_on_challenge(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if not ctx.challenge_detected:
        return None
    if p.pause_on_captcha:
        return Fired(
            "The portal raised a CAPTCHA or identity check. The session is waiting for you "
            "to complete it — the agent will not attempt to solve or bypass it.",
            verdict=Verdict.ESCALATE,
        )
    # Not solving it is not optional; the only choice is whether to wait for a human.
    return Fired(
        "The portal raised a CAPTCHA or identity check and 'pause on challenge' is off, so "
        "this application stops here. Turn it on to hand the session to yourself instead.",
        verdict=Verdict.BLOCK,
    )


# -- §2 volume and rate -----------------------------------------------------------------


def _tz(p: AutomationPolicy) -> ZoneInfo:
    """The operator's timezone, falling back to UTC on an unknown name.

    A bad timezone string must not take the whole gate down — that would fail *open* for
    every rule evaluated after it.
    """
    try:
        return ZoneInfo(p.run_window.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def _next_midnight(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    tomorrow = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.astimezone(UTC)


def _daily_cap(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if p.max_per_day <= 0 or ctx.submitted_today < p.max_per_day:
        return None
    return Fired(
        f"Daily cap reached ({ctx.submitted_today}/{p.max_per_day} today). "
        "This application stays queued and goes out tomorrow.",
        retry_after=_next_midnight(ctx.now, _tz(p)),
    )


def _hourly_cap(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if p.max_per_hour <= 0 or ctx.submitted_this_hour < p.max_per_hour:
        return None
    next_hour = (ctx.now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return Fired(
        f"Hourly cap reached ({ctx.submitted_this_hour}/{p.max_per_hour} this hour). "
        "Queued until the next hour.",
        retry_after=next_hour,
    )


def _min_spacing(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    gap = ctx.seconds_since_last_submission
    if p.min_seconds_between <= 0 or gap is None or gap >= p.min_seconds_between:
        return None
    wait = p.min_seconds_between - gap
    return Fired(
        f"Last submission was {gap}s ago; the policy spaces them {p.min_seconds_between}s "
        f"apart. Sending in about {wait}s.",
        retry_after=ctx.now + timedelta(seconds=wait),
    )


def _per_company_week(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if p.max_per_company_per_week <= 0:
        return None
    if ctx.submitted_to_company_this_week < p.max_per_company_per_week:
        return None
    return Fired(
        f"Already applied to {ctx.company or 'this employer'} "
        f"{ctx.submitted_to_company_this_week} times in the last 7 days "
        f"(cap {p.max_per_company_per_week}). Held so it does not read as a mailshot.",
        retry_after=ctx.now + timedelta(days=1),
    )


# -- §3 duplicate suppression -----------------------------------------------------------


def _same_posting(_p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if not ctx.duplicate_of_application_id:
        return None
    return Fired(
        f"You have already applied to this exact posting "
        f"(application {ctx.duplicate_of_application_id}). Applying twice is never useful."
    )


def _reapply_cooldown(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    last = ctx.last_similar_application_at
    if p.reapply_cooldown_days <= 0 or last is None:
        return None
    clears = last + timedelta(days=p.reapply_cooldown_days)
    if ctx.now >= clears:
        return None
    days_left = max(1, (clears - ctx.now).days)
    return Fired(
        f"A similar role at {ctx.company or 'this employer'} was applied to "
        f"{(ctx.now - last).days} days ago; the cooldown is {p.reapply_cooldown_days} days. "
        f"Held for another {days_left}.",
        retry_after=clears,
    )


# -- §4 human oversight -----------------------------------------------------------------


def _kill_switch(p: AutomationPolicy, _ctx: PolicyContext) -> Fired | None:
    if not p.paused:
        return None
    return Fired(
        "Automation is paused. Everything stays queued and nothing is submitted until you "
        "resume it."
    )


def _high_value_review(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    threshold = p.require_review_above_salary_k
    if threshold <= 0 or ctx.salary_max_k is None or ctx.salary_max_k < threshold:
        return None
    return Fired(
        f"This role pays up to £{ctx.salary_max_k}k, above your £{threshold}k review "
        "threshold. Read it before it goes out.",
        verdict=Verdict.ESCALATE,
    )


def _new_portal_first_run(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if not (p.review_first_run_per_source and ctx.first_run_on_source):
        return None
    return Fired(
        f"First application through {ctx.source_key or 'this portal'}. Form handling is "
        "least reliable on a portal never used before, so this one wants your eyes.",
        verdict=Verdict.ESCALATE,
    )


# -- §5 match and eligibility -----------------------------------------------------------


def _min_ats(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if ctx.ats_score is None:
        # Not "scored zero" — not scored. Passing an unscored application would make the
        # gate silently optional whenever the scorer is unavailable.
        return Fired(
            "This posting could not be scored against your CV, so the match gate cannot be "
            "applied. Check it yourself before it goes out.",
            verdict=Verdict.ESCALATE,
        )
    if ctx.ats_score >= p.min_ats_score:
        return None
    return Fired(
        f"ATS match {ctx.ats_score:.0%} is below your {p.min_ats_score:.0%} threshold. "
        "Tailor the CV or lower the threshold and it will go out.",
    )


def _salary_floor(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    # A posting with no published band is kept, not dropped — most UK postings omit one, and
    # filtering on absence would discard the majority of the market.
    if p.min_salary_k <= 0 or ctx.salary_max_k is None:
        return None
    if ctx.salary_max_k >= p.min_salary_k:
        return None
    return Fired(
        f"Pays up to £{ctx.salary_max_k}k, below your £{p.min_salary_k}k floor."
    )


def _seniority(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    if not p.seniority or not ctx.seniority:
        return None
    if ctx.seniority in p.seniority:
        return None
    return Fired(
        f"Reads as a {ctx.seniority} role; you are targeting {', '.join(p.seniority)}."
    )


def _blocked_employer(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    company = (ctx.company or "").casefold()
    if not company:
        return None
    for blocked in p.blocked_companies:
        if blocked.strip() and blocked.strip().casefold() in company:
            return Fired(f"{ctx.company} is on your blocked-employers list.")
    return None


# -- §6 run window ----------------------------------------------------------------------


def _next_window_open(p: AutomationPolicy, now: datetime) -> datetime:
    """The next moment the run window is open, searching forward a week.

    A week is enough: the window either opens within seven days or the operator has selected
    no days at all, which is handled before this is called.
    """
    tz = _tz(p)
    local = now.astimezone(tz)
    days = p.run_window.days or list(_DAYS)
    start_h, start_m = _parse_hhmm(p.run_window.start, 0, 0)
    for offset in range(8):
        day = local + timedelta(days=offset)
        if _DAYS[day.weekday()] not in days:
            continue
        candidate = day.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        if candidate > local:
            return candidate.astimezone(UTC)
    return (now + timedelta(days=1)).astimezone(UTC)


def _parse_hhmm(value: str, default_h: int, default_m: int) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not match:
        return default_h, default_m
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default_h, default_m
    return hour, minute


def _run_window(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    window = p.run_window
    local = ctx.now.astimezone(_tz(p))
    days = window.days or list(_DAYS)
    start_h, start_m = _parse_hhmm(window.start, 0, 0)
    end_h, end_m = _parse_hhmm(window.end, 23, 59)
    minutes = local.hour * 60 + local.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m

    day_ok = _DAYS[local.weekday()] in days
    # An end before the start is an overnight window (22:00-04:00), not an empty one.
    time_ok = start <= minutes < end if start <= end else (minutes >= start or minutes < end)
    if day_ok and time_ok:
        return None
    return Fired(
        f"Outside your run window ({', '.join(days)} {window.start}-{window.end} "
        f"{window.timezone}). Queued until it opens.",
        retry_after=_next_window_open(p, ctx.now),
    )


# -- §7 failure handling ----------------------------------------------------------------


def _circuit_breaker(p: AutomationPolicy, ctx: PolicyContext) -> Fired | None:
    limit = p.circuit_breaker_failures
    if limit <= 0 or ctx.consecutive_source_failures < limit:
        return None
    return Fired(
        f"{ctx.source_key or 'This portal'} has failed {ctx.consecutive_source_failures} "
        f"times in a row, so it is suspended. Something upstream changed — retrying it "
        "harder will not fix it.",
        retry_after=ctx.now + timedelta(hours=1),
    )


# -- the catalogue ----------------------------------------------------------------------

RULES: tuple[Rule, ...] = (
    # §1 — locked invariants. See docs/AUTOMATION_POLICY.md §1.
    Rule(
        id="integrity.no_fabrication",
        clause="§1.1",
        title="Never invent experience",
        rationale=(
            "The agent may reorder, re-weight and re-word what is in your CV repository. It "
            "may not invent an employer, date, title, qualification or metric. Enforced at "
            "the generator, not filtered afterwards."
        ),
        enforcement=Enforcement.ELSEWHERE,
        enforced_by="app.services.resume — tailoring is capped at fabrication level 4",
        control=LOCKED,
        tags=("integrity",),
    ),
    Rule(
        id="integrity.no_auto_eligibility_answers",
        clause="§1.2",
        title="Eligibility questions are never auto-answered",
        rationale=(
            "Right to work, visa status, sponsorship, clearance, protected characteristics, "
            "notice period and salary expectation are answered by you or not at all. A wrong "
            "answer is a misrepresentation to an employer."
        ),
        enforcement=Enforcement.GATE,
        control=LOCKED,
        verdict=Verdict.ESCALATE,
        check=_no_auto_eligibility,
        tags=("integrity",),
    ),
    Rule(
        id="integrity.no_bot_circumvention",
        clause="§1.3",
        title="No bot-protection circumvention",
        rationale=(
            "CAPTCHAs and device checks are access decisions and are respected as such. The "
            "agent does not solve, farm out or evade them, and does not rotate credentials "
            "to get around a rate limit."
        ),
        enforcement=Enforcement.ELSEWHERE,
        enforced_by="no solver is integrated; challenges route to oversight.pause_on_challenge",
        control=LOCKED,
        tags=("integrity",),
    ),
    Rule(
        id="integrity.single_identity",
        clause="§1.4",
        title="One identity",
        rationale=(
            "Applications go out under your real name and contact details. No aliases, no "
            "throwaway identities, no applying on behalf of anyone else."
        ),
        enforcement=Enforcement.ELSEWHERE,
        enforced_by="app.services.application — the profile is read from the account owner",
        control=LOCKED,
        tags=("integrity",),
    ),
    Rule(
        id="integrity.disclose_ai_assistance",
        clause="§1.5",
        title="Disclose AI assistance",
        rationale=(
            "Off by default: no jurisdiction requires it and most employers do not ask. Where "
            "an employer does ask, §1.2 applies and the question is escalated to you."
        ),
        enforcement=Enforcement.BEHAVIOUR,
        control=TOGGLE,
        field_name="disclose_ai_assistance",
        tags=("integrity",),
    ),
    # §2 — volume and rate.
    Rule(
        id="volume.daily_cap",
        clause="§2.1",
        title="Applications per day",
        rationale=(
            "Above a considered human pace, below anything a portal reads as scripted. The "
            "target is interview probability, not throughput."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.INTEGER, min=0, max=200, step=1, unit="per day", off_value=0
        ),
        field_name="max_per_day",
        check=_daily_cap,
        tags=("volume",),
    ),
    Rule(
        id="volume.hourly_cap",
        clause="§2.2",
        title="Applications per hour",
        rationale=(
            "The daily cap alone permits twenty applications in four minutes, which no human "
            "does. This is the rule that makes the daily one credible."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.INTEGER, min=0, max=50, step=1, unit="per hour", off_value=0
        ),
        field_name="max_per_hour",
        check=_hourly_cap,
        tags=("volume",),
    ),
    Rule(
        id="volume.min_spacing",
        clause="§2.3",
        title="Minimum gap between submissions",
        rationale=(
            "Uniform sub-second timing is the clearest bot signature in a portal's logs."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.SECONDS, min=0, max=3600, step=15, unit="seconds", off_value=0
        ),
        field_name="min_seconds_between",
        check=_min_spacing,
        tags=("volume",),
    ),
    Rule(
        id="volume.per_company_week",
        clause="§2.4",
        title="Applications to one employer per week",
        rationale="Six applications to one employer in a week does not read as enthusiasm.",
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.INTEGER, min=0, max=20, step=1, unit="per 7 days", off_value=0
        ),
        field_name="max_per_company_per_week",
        check=_per_company_week,
        tags=("volume",),
    ),
    # §3 — duplicates.
    Rule(
        id="duplicates.same_posting",
        clause="§3.1",
        title="Never apply twice to the same posting",
        rationale=(
            "The most visible possible automation failure, and the fastest route to being "
            "ignored by a recruiter. Not a preference."
        ),
        enforcement=Enforcement.GATE,
        control=LOCKED,
        verdict=Verdict.BLOCK,
        check=_same_posting,
        tags=("duplicates",),
    ),
    Rule(
        id="duplicates.reapply_cooldown",
        clause="§3.2",
        title="Re-application cooldown",
        rationale=(
            "How long before a materially similar role at the same employer may be applied "
            "to again. Held rather than dropped — the cooldown does expire."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.DAYS, min=0, max=730, step=15, unit="days", off_value=0
        ),
        field_name="reapply_cooldown_days",
        check=_reapply_cooldown,
        tags=("duplicates",),
    ),
    # §4 — human oversight.
    Rule(
        id="oversight.kill_switch",
        clause="§4.2",
        title="Pause all automation",
        rationale=(
            "'How do I make it stop right now' needs an answer that is not 'kill the "
            "worker'. Everything queued stays queued."
        ),
        enforcement=Enforcement.GATE,
        control=TOGGLE,
        field_name="paused",
        check=_kill_switch,
        tags=("oversight",),
    ),
    Rule(
        id="oversight.high_value_review",
        clause="§4.3",
        title="Review roles above",
        rationale=(
            "The cost of a bad automated application scales with the role, so high-stakes "
            "ones get a human look regardless of apply mode."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.MONEY_K, min=0, max=500, step=10, unit="£k", off_value=0
        ),
        field_name="require_review_above_salary_k",
        verdict=Verdict.ESCALATE,
        check=_high_value_review,
        tags=("oversight",),
    ),
    Rule(
        id="oversight.new_portal_first_run",
        clause="§4.4",
        title="Review the first run on a new portal",
        rationale=(
            "Form-filling is the least reliable part of the system, and the first submission "
            "through a portal is where an unseen field shows up."
        ),
        enforcement=Enforcement.GATE,
        control=TOGGLE,
        field_name="review_first_run_per_source",
        verdict=Verdict.ESCALATE,
        check=_new_portal_first_run,
        tags=("oversight",),
    ),
    Rule(
        id="oversight.pause_on_challenge",
        clause="§4.5",
        title="Hand the session over on a CAPTCHA",
        rationale=(
            "Solving it is never an option (§1.3). This is only the choice between waiting "
            "for you and stopping: off means the application ends there."
        ),
        enforcement=Enforcement.GATE,
        control=TOGGLE,
        field_name="pause_on_captcha",
        verdict=Verdict.ESCALATE,
        check=_pause_on_challenge,
        tags=("oversight",),
    ),
    # §5 — match and eligibility.
    Rule(
        id="match.min_ats_score",
        clause="§5.1",
        title="Minimum ATS match",
        rationale=(
            "The system does not apply to roles it cannot argue for. Below this a posting is "
            "still collected, scored and shown — it is only not auto-applied to."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(kind=ControlKind.PERCENT, min=0, max=95, step=5, unit="%"),
        field_name="min_ats_score",
        check=_min_ats,
        tags=("match",),
    ),
    Rule(
        id="match.salary_floor",
        clause="§5.2",
        title="Minimum salary",
        rationale=(
            "Postings without a published band are kept and flagged, not dropped — most UK "
            "postings omit one, and filtering on absence discards most of the market."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.MONEY_K, min=0, max=300, step=5, unit="£k", off_value=0
        ),
        field_name="min_salary_k",
        check=_salary_floor,
        tags=("match",),
    ),
    Rule(
        id="match.seniority",
        clause="§5.3",
        title="Seniority band",
        rationale=(
            "Read from the posting's own experience level, which many boards leave "
            "blank. An empty selection means any seniority, and a posting that declares "
            "none is never filtered out on a guess."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.MULTI_CHOICE, options=list(SENIORITY_LEVELS), off_value=[]
        ),
        field_name="seniority",
        check=_seniority,
        tags=("match",),
    ),
    Rule(
        id="match.blocked_employer",
        clause="§5.4",
        title="Blocked employers",
        rationale="Matched case-insensitively anywhere in the company name.",
        enforcement=Enforcement.GATE,
        control=ControlSpec(kind=ControlKind.TEXT_LIST, off_value=[]),
        field_name="blocked_companies",
        verdict=Verdict.BLOCK,
        check=_blocked_employer,
        tags=("match",),
    ),
    # §6 — run window.
    Rule(
        id="window.run_window",
        clause="§6",
        title="Run window",
        rationale=(
            "A 03:00 application timestamp is a tell, and working hours mean you are awake "
            "to handle anything that escalates. Outside it, everything queues."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(kind=ControlKind.WEEKDAYS, options=list(_DAYS)),
        field_name="run_window",
        check=_run_window,
        tags=("window",),
    ),
    # §7 — failure handling.
    Rule(
        id="failure.circuit_breaker",
        clause="§7.2",
        title="Suspend a portal after consecutive failures",
        rationale=(
            "Continuing to hammer a broken integration produces nothing but noise in someone "
            "else's logs."
        ),
        enforcement=Enforcement.GATE,
        control=ControlSpec(
            kind=ControlKind.INTEGER, min=0, max=20, step=1, unit="failures", off_value=0
        ),
        field_name="circuit_breaker_failures",
        check=_circuit_breaker,
        tags=("failure",),
    ),
    Rule(
        id="failure.retry_failed",
        clause="§7.1",
        title="Retry failed submissions",
        rationale=(
            "Only failures classified as transient are retried. A form that rejected the "
            "submission is not — retrying submits the same wrong thing again."
        ),
        enforcement=Enforcement.BEHAVIOUR,
        control=TOGGLE,
        field_name="retry_failed",
        tags=("failure",),
    ),
    Rule(
        id="failure.max_retries",
        clause="§7.1",
        title="Maximum retries",
        rationale="Attempts per application, backed off between each.",
        enforcement=Enforcement.BEHAVIOUR,
        control=ControlSpec(
            kind=ControlKind.INTEGER, min=0, max=10, step=1, unit="attempts", off_value=0
        ),
        field_name="max_retries",
        tags=("failure",),
    ),
    Rule(
        id="failure.email_fallback",
        clause="§7.3",
        title="Email-apply fallback",
        rationale=(
            "Only ever used where the posting itself publishes an application address. Never "
            "an address found elsewhere."
        ),
        enforcement=Enforcement.BEHAVIOUR,
        control=TOGGLE,
        field_name="email_fallback",
        tags=("failure",),
    ),
    Rule(
        id="failure.notify_each_outcome",
        clause="§7",
        title="Notify on every outcome",
        rationale="Success and failure notifications for each application.",
        enforcement=Enforcement.BEHAVIOUR,
        control=TOGGLE,
        field_name="notify_each_outcome",
        tags=("failure",),
    ),
    # §8 — data protection.
    Rule(
        id="privacy.redact_pii",
        clause="§8.2",
        title="Redact personal data from logs and prompts",
        rationale=(
            "Names, addresses, phone numbers and email addresses never reach a log line or "
            "an LLM prompt. The gate fails closed: an unclassifiable string is treated as "
            "personal data."
        ),
        enforcement=Enforcement.ELSEWHERE,
        enforced_by="app.core.privacy — the PII gate",
        control=LOCKED,
        tags=("privacy",),
    ),
    Rule(
        id="privacy.retain_documents_days",
        clause="§8.3",
        title="Keep generated documents for",
        rationale=(
            "Generated CVs and cover letters are your own documents, so the default keeps "
            "them indefinitely. They are deleted with the account either way."
        ),
        enforcement=Enforcement.BEHAVIOUR,
        control=ControlSpec(
            kind=ControlKind.DAYS, min=0, max=3650, step=30, unit="days", off_value=0
        ),
        field_name="retain_documents_days",
        tags=("privacy",),
    ),
    # Documents — not a numbered clause; the résumé-rule table has its own bespoke UI.
    Rule(
        id="documents.cover_letters",
        clause="—",
        title="Generate a cover letter for every application",
        rationale=(
            "A letter is generated per posting from your own material and the job text. "
            "Off means apply with the CV alone, which is the right choice for portals "
            "that ignore the field."
        ),
        enforcement=Enforcement.BEHAVIOUR,
        control=TOGGLE,
        field_name="cover_letters",
        tags=("documents",),
    ),
    Rule(
        id="documents.cover_letter_tone",
        clause="—",
        title="Cover letter tone",
        rationale="Sets the register of the generated letter.",
        enforcement=Enforcement.BEHAVIOUR,
        control=ControlSpec(
            kind=ControlKind.CHOICE, options=["direct", "warm", "formal", "technical"]
        ),
        field_name="cover_letter_tone",
        tags=("documents",),
    ),
)

BY_ID: dict[str, Rule] = {r.id: r for r in RULES}

#: The rules actually evaluated before a submission, in catalogue order.
GATES: tuple[Rule, ...] = tuple(r for r in RULES if r.enforcement is Enforcement.GATE)

#: Human-readable group names, in the order the UI should show them.
TAG_TITLES: tuple[tuple[str, str], ...] = (
    ("oversight", "Human oversight"),
    ("match", "Match & eligibility"),
    ("volume", "Volume & rate"),
    ("duplicates", "Duplicates"),
    ("window", "Run window"),
    ("failure", "Failure handling"),
    ("documents", "Documents"),
    ("privacy", "Data protection"),
    ("integrity", "Integrity — not configurable"),
)
