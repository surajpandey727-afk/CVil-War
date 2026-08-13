"""The automation policy — what the agent is allowed to do, as enforced code.

The prose standard is ``docs/AUTOMATION_POLICY.md``; every clause in it names a rule in
:mod:`app.core.policy.rules`, and ``tests/unit/test_policy_catalogue.py`` fails if the two
drift apart. Nothing here touches the database — see :mod:`app.services.policy` for the layer
that assembles a :class:`PolicyContext` and records the decision.
"""

from app.core.policy.engine import evaluate
from app.core.policy.model import (
    POLICY_VERSION,
    AutomationPolicy,
    ControlKind,
    ControlSpec,
    PolicyContext,
    PolicyDecision,
    ResumeRule,
    RuleOutcome,
    RunWindow,
    Verdict,
)
from app.core.policy.rules import BY_ID, GATES, RULES, TAG_TITLES, Enforcement, Rule

__all__ = [
    "BY_ID",
    "GATES",
    "POLICY_VERSION",
    "RULES",
    "TAG_TITLES",
    "AutomationPolicy",
    "ControlKind",
    "ControlSpec",
    "Enforcement",
    "PolicyContext",
    "PolicyDecision",
    "ResumeRule",
    "Rule",
    "RuleOutcome",
    "RunWindow",
    "Verdict",
    "evaluate",
]
