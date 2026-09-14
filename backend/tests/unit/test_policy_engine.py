"""The policy engine — verdicts, fail-closed behaviour, and the individual rules.

Every test here fixes ``ctx.now`` explicitly. A run-window rule tested against the wall clock
passes or fails depending on what time CI runs, which is worse than not testing it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.policy import AutomationPolicy, PolicyContext, RunWindow, Verdict, evaluate
from app.core.policy.model import ControlKind, ControlSpec
from app.core.policy.rules import GATES, Enforcement, Fired, Rule

#: A Wednesday at 10:00 UTC — inside the default Mon-Fri 08:00-19:00 window.
INSIDE_WINDOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def ctx(**overrides) -> PolicyContext:  # type: ignore[no-untyped-def]
    """A context that passes every rule, so each test changes exactly one thing."""
    base = {
        "now": INSIDE_WINDOW,
        "job_title": "Product Manager",
        "company": "Monzo",
        "source_key": "careers:monzo",
        "ats_score": 0.9,
        "first_run_on_source": False,
    }
    return PolicyContext(**{**base, **overrides})


class TestVerdicts:
    def test_a_clean_application_is_allowed(self) -> None:
        decision = evaluate(AutomationPolicy(), ctx())
        assert decision.verdict is Verdict.ALLOW
        assert decision.outcomes == []
        assert decision.allowed

    def test_the_most_restrictive_verdict_wins(self) -> None:
        """A blocked employer and a rate cap at once is a BLOCK, not a HOLD."""
        policy = AutomationPolicy(blocked_companies=["Monzo"], max_per_day=1)
        decision = evaluate(policy, ctx(submitted_today=5))
        assert decision.verdict is Verdict.BLOCK

    def test_every_objecting_rule_is_reported_not_just_the_first(self) -> None:
        """An operator asking why this has not gone out deserves the whole answer.

        Stopping at the first objection turns one question into four rounds of fix-and-retry,
        which is the dead end the product exists to remove.
        """
        policy = AutomationPolicy(max_per_day=1, min_salary_k=200, min_ats_score=0.95)
        decision = evaluate(policy, ctx(submitted_today=9, salary_max_k=80, ats_score=0.5))
        fired = {o.rule_id for o in decision.outcomes}
        assert {"volume.daily_cap", "match.salary_floor", "match.min_ats_score"} <= fired

    def test_the_summary_puts_the_most_severe_reason_first(self) -> None:
        policy = AutomationPolicy(blocked_companies=["Monzo"], max_per_day=1)
        decision = evaluate(policy, ctx(submitted_today=5))
        assert decision.summary.startswith("Monzo is on your blocked-employers list")


class TestFailsClosed:
    def test_a_rule_that_raises_escalates_rather_than_passing(self) -> None:
        """The PII gate in this codebase was once found returning False on exception, which
        turned a guard into a no-op exactly when it was needed. The same mistake here would
        submit applications under a policy that had quietly stopped applying."""

        def explode(_p: AutomationPolicy, _c: PolicyContext) -> Fired | None:
            raise RuntimeError("upstream lookup failed")

        broken = Rule(
            id="test.explodes",
            clause="§0",
            title="Deliberately broken",
            rationale="x" * 50,
            enforcement=Enforcement.GATE,
            control=ControlSpec(kind=ControlKind.TOGGLE),
            field_name="paused",
            check=explode,
            tags=("oversight",),
        )
        decision = evaluate(AutomationPolicy(), ctx(), rules=(broken,))
        assert decision.verdict is Verdict.ESCALATE
        assert "could not be evaluated" in decision.outcomes[0].reason

    def test_an_unscored_application_escalates_rather_than_slipping_through(self) -> None:
        """The gate this replaced returned ``(True, 0.0)`` whenever scoring was unavailable,
        so a missing scorer silently made the ATS threshold optional. ``None`` is 'not
        scored', which is a question for a human, not a pass."""
        decision = evaluate(AutomationPolicy(), ctx(ats_score=None))
        assert decision.verdict is Verdict.ESCALATE
        assert decision.outcomes[0].rule_id == "match.min_ats_score"
        # Deliberately handled, not merely survived: deleting the None branch would make the
        # comparison raise and reach the same verdict down the fail-closed path, so the
        # assertion has to distinguish the two.
        assert "could not be scored" in decision.outcomes[0].reason

    def test_a_zero_score_is_still_a_score_and_is_refused(self) -> None:
        """0.0 and None must not be conflated in the other direction either."""
        decision = evaluate(AutomationPolicy(), ctx(ats_score=0.0))
        assert decision.verdict is Verdict.HOLD

    def test_an_unknown_timezone_does_not_open_the_gate(self) -> None:
        """A bad timezone string must degrade to UTC, not throw the run window away."""
        policy = AutomationPolicy(
            run_window=RunWindow(days=["Mon"], start="08:00", end="09:00", timezone="Mars/Olympus")
        )
        decision = evaluate(policy, ctx())  # a Wednesday
        assert decision.verdict is Verdict.HOLD
        assert decision.outcomes[0].rule_id == "window.run_window"


class TestHoldIsNotBlock:
    """The distinction is load-bearing: one comes back, the other never does."""

    def test_outside_the_run_window_holds_and_says_when_it_clears(self) -> None:
        saturday = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        decision = evaluate(AutomationPolicy(), ctx(now=saturday))
        assert decision.verdict is Verdict.HOLD
        assert decision.retry_after is not None
        assert decision.retry_after > saturday

    def test_a_blocked_employer_is_terminal_and_offers_no_retry(self) -> None:
        policy = AutomationPolicy(blocked_companies=["monzo"])
        decision = evaluate(policy, ctx())
        assert decision.verdict is Verdict.BLOCK
        assert decision.retry_after is None

    def test_a_duplicate_posting_is_blocked_not_held(self) -> None:
        decision = evaluate(AutomationPolicy(), ctx(duplicate_of_application_id="abc123"))
        assert decision.verdict is Verdict.BLOCK

    def test_retry_after_is_the_earliest_of_several_holds(self) -> None:
        """The application wakes as soon as any single hold could have lifted, and is simply
        re-evaluated then — waiting for the last one would strand it for the longest reason."""
        policy = AutomationPolicy(max_per_day=1, min_seconds_between=120)
        decision = evaluate(
            policy, ctx(submitted_today=5, seconds_since_last_submission=10)
        )
        assert decision.verdict is Verdict.HOLD
        # Spacing clears in ~110s; the daily cap not until midnight.
        assert decision.retry_after == INSIDE_WINDOW + timedelta(seconds=110)


class TestVolumeRules:
    def test_the_daily_cap_holds_at_the_limit_not_past_it(self) -> None:
        policy = AutomationPolicy(max_per_day=20)
        assert evaluate(policy, ctx(submitted_today=19)).verdict is Verdict.ALLOW
        assert evaluate(policy, ctx(submitted_today=20)).verdict is Verdict.HOLD

    def test_a_zero_cap_disables_the_rule_rather_than_blocking_everything(self) -> None:
        """0 is the documented 'off' value for every numeric limit. Reading it as a literal
        limit of zero would silently stop all automation the moment someone dragged a slider
        to the bottom."""
        policy = AutomationPolicy(max_per_day=0, max_per_hour=0, max_per_company_per_week=0)
        decision = evaluate(policy, ctx(submitted_today=999, submitted_this_hour=999))
        assert decision.verdict is Verdict.ALLOW

    def test_spacing_is_not_enforced_when_nothing_has_been_submitted_yet(self) -> None:
        """No previous submission is ``None``, not a gap of zero seconds — otherwise the very
        first application of the account would be held for no reason."""
        policy = AutomationPolicy(min_seconds_between=90)
        assert evaluate(policy, ctx(seconds_since_last_submission=None)).verdict is Verdict.ALLOW
        assert evaluate(policy, ctx(seconds_since_last_submission=0)).verdict is Verdict.HOLD

    def test_the_per_employer_cap_names_the_employer(self) -> None:
        policy = AutomationPolicy(max_per_company_per_week=2)
        decision = evaluate(policy, ctx(submitted_to_company_this_week=2))
        assert "Monzo" in decision.outcomes[0].reason


class TestMatchRules:
    def test_a_posting_with_no_published_band_is_not_dropped(self) -> None:
        """Most UK postings omit a salary. Treating absence as below the floor would discard
        the majority of the market."""
        policy = AutomationPolicy(min_salary_k=80)
        assert evaluate(policy, ctx(salary_max_k=None)).verdict is Verdict.ALLOW
        assert evaluate(policy, ctx(salary_max_k=60)).verdict is Verdict.HOLD

    def test_a_posting_that_declares_no_seniority_is_not_filtered_on_a_guess(self) -> None:
        policy = AutomationPolicy(seniority=["Senior", "Lead"])
        assert evaluate(policy, ctx(seniority="")).verdict is Verdict.ALLOW
        assert evaluate(policy, ctx(seniority="Junior")).verdict is Verdict.HOLD
        assert evaluate(policy, ctx(seniority="Senior")).verdict is Verdict.ALLOW

    def test_blocked_employers_match_case_insensitively_inside_the_name(self) -> None:
        policy = AutomationPolicy(blocked_companies=["MONZO"])
        assert evaluate(policy, ctx(company="Monzo Bank Ltd")).verdict is Verdict.BLOCK

    def test_a_blank_entry_in_the_blocked_list_does_not_block_everything(self) -> None:
        """A trailing comma in the UI's comma-separated field produces an empty string, and
        ``"" in anything`` is True — which would block every employer."""
        policy = AutomationPolicy(blocked_companies=["", "  "])
        assert evaluate(policy, ctx()).verdict is Verdict.ALLOW


class TestExcludeNoSponsorship:
    """Off by default; only fires on an explicit refusal (``not_sponsor``), never on the far
    more common ``unknown`` (a posting that simply never mentions sponsorship)."""

    def test_off_by_default_even_on_an_explicit_refusal(self) -> None:
        decision = evaluate(AutomationPolicy(), ctx(sponsor_confidence="not_sponsor"))
        assert decision.verdict is Verdict.ALLOW

    def test_blocks_an_explicit_refusal_when_turned_on(self) -> None:
        policy = AutomationPolicy(exclude_no_sponsorship=True)
        decision = evaluate(policy, ctx(sponsor_confidence="not_sponsor"))
        assert decision.verdict is Verdict.BLOCK

    def test_never_fires_on_plain_unknown_even_when_turned_on(self) -> None:
        """The posting that never mentions sponsorship at all — the common case — must never
        be treated the same as one that explicitly refuses."""
        policy = AutomationPolicy(exclude_no_sponsorship=True)
        decision = evaluate(policy, ctx(sponsor_confidence="unknown"))
        assert decision.verdict is Verdict.ALLOW

    def test_confirmed_sponsor_is_unaffected_when_turned_on(self) -> None:
        policy = AutomationPolicy(exclude_no_sponsorship=True)
        decision = evaluate(policy, ctx(sponsor_confidence="confirmed_register"))
        assert decision.verdict is Verdict.ALLOW


class TestRunWindow:
    def test_an_overnight_window_is_not_read_as_an_empty_one(self) -> None:
        """22:00-04:00 wraps midnight. A naive ``start <= now < end`` makes it always false,
        which would hold every application forever."""
        policy = AutomationPolicy(
            run_window=RunWindow(days=list(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
                                 start="22:00", end="04:00", timezone="UTC")
        )
        at_2330 = datetime(2026, 8, 12, 23, 30, tzinfo=UTC)
        at_0200 = datetime(2026, 8, 13, 2, 0, tzinfo=UTC)
        at_1200 = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
        assert evaluate(policy, ctx(now=at_2330)).verdict is Verdict.ALLOW
        assert evaluate(policy, ctx(now=at_0200)).verdict is Verdict.ALLOW
        assert evaluate(policy, ctx(now=at_1200)).verdict is Verdict.HOLD

    def test_the_window_is_evaluated_in_the_operators_timezone(self) -> None:
        """09:00 London is 08:00 UTC. Evaluating in UTC would refuse the first hour of the
        working day for half the year and accept an hour too early for the other half."""
        policy = AutomationPolicy(
            run_window=RunWindow(days=["Wed"], start="09:00", end="17:00",
                                 timezone="Europe/London")
        )
        # 08:30 UTC == 09:30 BST on this date — inside the window.
        assert evaluate(policy, ctx(now=datetime(2026, 8, 12, 8, 30, tzinfo=UTC))).allowed
        # 07:30 UTC == 08:30 BST — outside.
        assert not evaluate(policy, ctx(now=datetime(2026, 8, 12, 7, 30, tzinfo=UTC))).allowed

    def test_an_empty_day_list_means_every_day(self) -> None:
        policy = AutomationPolicy(run_window=RunWindow(days=[], timezone="UTC"))
        sunday = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
        assert evaluate(policy, ctx(now=sunday)).verdict is Verdict.ALLOW

    def test_the_next_open_time_lands_inside_the_window(self) -> None:
        policy = AutomationPolicy(
            run_window=RunWindow(days=["Mon"], start="08:00", end="19:00", timezone="UTC")
        )
        saturday = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        decision = evaluate(policy, ctx(now=saturday))
        reopened = decision.retry_after
        assert reopened is not None
        assert reopened.weekday() == 0 and reopened.hour == 8
        # And the application is genuinely allowed at that moment.
        assert evaluate(policy, ctx(now=reopened + timedelta(minutes=1))).allowed


class TestOversight:
    def test_the_kill_switch_holds_everything(self) -> None:
        decision = evaluate(AutomationPolicy(paused=True), ctx())
        assert decision.verdict is Verdict.HOLD
        assert decision.outcomes[0].rule_id == "oversight.kill_switch"

    def test_a_high_value_role_escalates_rather_than_being_refused(self) -> None:
        policy = AutomationPolicy(require_review_above_salary_k=120)
        assert evaluate(policy, ctx(salary_max_k=150)).verdict is Verdict.ESCALATE
        assert evaluate(policy, ctx(salary_max_k=90)).verdict is Verdict.ALLOW

    def test_the_first_run_on_a_portal_wants_a_human(self) -> None:
        assert evaluate(AutomationPolicy(), ctx(first_run_on_source=True)).verdict is (
            Verdict.ESCALATE
        )

    def test_an_eligibility_question_always_escalates_however_the_policy_is_set(self) -> None:
        """§1.2 is an invariant: there is no field that switches it off, so a policy with
        every optional control disabled still refuses to answer for the operator."""
        permissive = AutomationPolicy(
            max_per_day=0, max_per_hour=0, min_seconds_between=0, min_ats_score=0.0,
            reapply_cooldown_days=0, review_first_run_per_source=False,
            require_review_above_salary_k=0, run_window=RunWindow(days=[], timezone="UTC"),
        )
        decision = evaluate(permissive, ctx(eligibility_questions=["Do you require visa sponsorship?"]))
        assert decision.verdict is Verdict.ESCALATE
        assert "visa sponsorship" in decision.summary


class TestChallengeHandling:
    def test_a_captcha_hands_the_session_over_when_that_is_wanted(self) -> None:
        decision = evaluate(AutomationPolicy(pause_on_captcha=True), ctx(challenge_detected=True))
        assert decision.verdict is Verdict.ESCALATE

    def test_turning_pause_off_stops_the_application_it_never_solves_the_challenge(self) -> None:
        """The toggle chooses between waiting for a human and giving up — never between
        respecting the challenge and bypassing it."""
        decision = evaluate(
            AutomationPolicy(pause_on_captcha=False), ctx(challenge_detected=True)
        )
        assert decision.verdict is Verdict.BLOCK
        assert "will not" in decision.summary or "stops here" in decision.summary


class TestCooldown:
    def test_a_recent_similar_application_holds_until_the_cooldown_expires(self) -> None:
        policy = AutomationPolicy(reapply_cooldown_days=90)
        applied = INSIDE_WINDOW - timedelta(days=30)
        decision = evaluate(policy, ctx(last_similar_application_at=applied))
        assert decision.verdict is Verdict.HOLD
        assert decision.retry_after == applied + timedelta(days=90)

    def test_an_expired_cooldown_lets_it_through(self) -> None:
        policy = AutomationPolicy(reapply_cooldown_days=90)
        applied = INSIDE_WINDOW - timedelta(days=120)
        assert evaluate(policy, ctx(last_similar_application_at=applied)).allowed


class TestCircuitBreaker:
    def test_a_repeatedly_failing_portal_is_suspended(self) -> None:
        policy = AutomationPolicy(circuit_breaker_failures=3)
        assert evaluate(policy, ctx(consecutive_source_failures=2)).allowed
        decision = evaluate(policy, ctx(consecutive_source_failures=3))
        assert decision.verdict is Verdict.HOLD
        assert "careers:monzo" in decision.outcomes[0].reason


class TestStoredPolicyCompatibility:
    def test_a_blob_written_before_the_engine_existed_still_loads(self) -> None:
        """The old settings screen persisted exactly this shape. It must validate and pick up
        defaults for every new clause, not fail and leave the operator with no policy."""
        legacy = {
            "min_ats_score": 0.8, "min_salary_k": 70, "seniority": ["Senior"],
            "blocked_companies": ["Acme"], "default_resume_id": None, "resume_rules": [],
            "cover_letters": True, "cover_letter_tone": "direct", "retry_failed": True,
            "max_retries": 3, "pause_on_captcha": True, "email_fallback": True,
            "notify_each_outcome": True,
            "run_window": {"days": ["Mon"], "start": "08:00", "end": "19:00",
                           "timezone": "Europe/London"},
            "enabled_sources": [],
        }
        policy = AutomationPolicy.model_validate(legacy)
        assert policy.min_ats_score == 0.8
        assert policy.max_per_day == 20  # new clause, defaulted
        assert policy.paused is False

    def test_a_clause_from_a_newer_build_is_ignored_rather_than_fatal(self) -> None:
        """Unknown means unenforced, which is the safe direction: an older build refusing to
        load the policy at all would leave the operator with no rules whatsoever."""
        policy = AutomationPolicy.model_validate({"max_per_day": 5, "not_a_clause_yet": 99})
        assert policy.max_per_day == 5

    def test_malformed_stored_string_list_entries_are_dropped_not_fatal(self) -> None:
        """Same crash class confirmed live for candidate_profile and role_targets: a
        malformed entry in a stored list clause must degrade, not 500 the whole
        settings response."""
        policy = AutomationPolicy.model_validate(
            {
                "seniority": [123, None, "senior"],
                "blocked_companies": "not a list",
                "resume_rules": [{"title_pattern": "x"}, "not a dict", None],
            }
        )
        assert policy.seniority == ["senior"]
        assert policy.blocked_companies == []
        assert len(policy.resume_rules) == 1
        assert policy.resume_rules[0].title_pattern == "x"


@pytest.mark.parametrize("rule", GATES, ids=lambda r: r.id)
def test_no_gate_rule_objects_to_a_clean_application(rule) -> None:  # type: ignore[no-untyped-def]
    """Sweeps for a rule whose default fires on the default context — which would make the
    system refuse everything out of the box."""
    assert rule.check is not None
    assert rule.check(AutomationPolicy(), ctx()) is None
