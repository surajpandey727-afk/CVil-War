"""Evaluate the automation policy against one candidate submission.

Pure: no database, no clock, no network. Everything the rules need arrives in the
:class:`PolicyContext`, which is what makes the whole gate testable without a fixture.

Two properties matter more than the rule logic itself.

**Every rule runs.** The evaluation does not stop at the first objection. An operator asking
"why hasn't this gone out?" deserves the whole answer, not the first of four reasons — three
more rounds of fix-and-retry is exactly the dead end the product is meant to remove.

**It fails closed.** A rule that raises is reported as an escalation, not skipped. The PII
gate in this codebase was once found returning ``False`` on exception, which turned a guard
into a no-op precisely when it was needed; the same mistake here would submit applications
under a policy that had silently stopped applying.
"""

from __future__ import annotations

import structlog

from app.core.policy.model import (
    AutomationPolicy,
    PolicyContext,
    PolicyDecision,
    RuleOutcome,
    Verdict,
    worst,
)
from app.core.policy.rules import GATES, Rule

logger = structlog.get_logger(__name__)


def evaluate(
    policy: AutomationPolicy, ctx: PolicyContext, *, rules: tuple[Rule, ...] = GATES
) -> PolicyDecision:
    """Decide whether this application may be submitted now.

    Returns the most restrictive verdict any rule produced, alongside *every* rule that
    objected. ``rules`` is injectable so a caller can evaluate a subset — the settings
    preview does this to show what the match rules alone would do.
    """
    outcomes: list[RuleOutcome] = []

    for rule in rules:
        if rule.check is None:  # not a gate; nothing to evaluate
            continue
        try:
            fired = rule.check(policy, ctx)
        except Exception as exc:
            # Fail closed. A rule that cannot evaluate has not given permission.
            logger.error("policy.rule_failed", rule_id=rule.id, error=str(exc))
            outcomes.append(
                RuleOutcome(
                    rule_id=rule.id,
                    clause=rule.clause,
                    verdict=Verdict.ESCALATE,
                    reason=(
                        f"The '{rule.title}' rule could not be evaluated ({exc}), so this "
                        "application needs your decision rather than an assumed yes."
                    ),
                )
            )
            continue
        if fired is None:
            continue
        outcomes.append(
            RuleOutcome(
                rule_id=rule.id,
                clause=rule.clause,
                verdict=fired.verdict or rule.verdict,
                reason=fired.reason,
                retry_after=fired.retry_after,
            )
        )

    verdict = worst([o.verdict for o in outcomes])
    # Only a HOLD has a meaningful retry time: an escalation clears when a human acts, and a
    # block never clears. Taking the earliest means the application wakes up as soon as any
    # single hold could have lifted, and is simply re-evaluated then.
    holds = [o.retry_after for o in outcomes if o.verdict is Verdict.HOLD and o.retry_after]
    return PolicyDecision(
        verdict=verdict,
        outcomes=outcomes,
        retry_after=min(holds) if holds and verdict is Verdict.HOLD else None,
        policy_version=policy.version,
    )
