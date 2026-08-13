"""The catalogue is the contract between the written policy, the engine and the UI.

Everything here guards the same failure: the three drifting apart. A policy document that
claims a rule the code does not enforce is worse than no document, and a rule the UI cannot
render is a setting the operator cannot reach.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest

from app.core.policy import RULES, TAG_TITLES, AutomationPolicy, ControlKind, Enforcement

POLICY_DOC = Path(__file__).resolve().parents[3] / "docs" / "AUTOMATION_POLICY.md"


#: A ``*Rule:*`` / ``*Rules:*`` block, which runs to the next blank line — the ids in a
#: multi-rule clause wrap, and a line-by-line reader silently misses every id after the
#: first wrap. That is exactly the kind of quiet under-reporting this file exists to catch,
#: so the parser has to span lines.
_RULE_BLOCK = re.compile(r"\*Rules?:\*(.*?)(?:\n\s*\n|\Z)", re.DOTALL)


def _rule_ids_named_in_the_document() -> set[str]:
    """Every rule id the prose policy claims is enforced."""
    text = POLICY_DOC.read_text(encoding="utf-8")
    ids: set[str] = set()
    for block in _RULE_BLOCK.findall(text):
        ids.update(re.findall(r"`([a-z_]+\.[a-z_]+)`", block))
    return ids


class TestDocumentAndCodeAgree:
    def test_the_policy_document_exists(self) -> None:
        assert POLICY_DOC.is_file(), f"{POLICY_DOC} is the policy; the code enforces it"

    def test_every_rule_the_document_claims_actually_exists(self) -> None:
        """A clause promising enforcement that no rule provides is a false claim."""
        claimed = _rule_ids_named_in_the_document()
        assert claimed, "parsed no rule ids from the document — the *Rule:* format changed"
        implemented = {r.id for r in RULES}
        assert claimed - implemented == set()

    def test_every_enforced_rule_is_written_down(self) -> None:
        """The reverse direction: a rule that silently refuses submissions and is documented
        nowhere is exactly the behaviour an operator cannot audit."""
        documented = _rule_ids_named_in_the_document()
        gates = {r.id for r in RULES if r.enforcement is Enforcement.GATE}
        assert gates - documented == set()


class TestCatalogueIntegrity:
    def test_rule_ids_are_unique(self) -> None:
        ids = [r.id for r in RULES]
        assert len(ids) == len(set(ids))

    def test_every_field_name_is_a_real_policy_field(self) -> None:
        """A typo here would silently read ``None`` and the rule would never fire."""
        fields = set(AutomationPolicy.model_fields)
        for rule in RULES:
            if rule.field_name:
                assert rule.field_name in fields, f"{rule.id} names a field that does not exist"

    def test_every_gate_rule_has_a_check(self) -> None:
        for rule in RULES:
            if rule.enforcement is Enforcement.GATE:
                assert rule.check is not None, f"{rule.id} claims to gate but checks nothing"

    def test_no_non_gate_rule_pretends_to_check(self) -> None:
        for rule in RULES:
            if rule.enforcement is not Enforcement.GATE:
                assert rule.check is None, f"{rule.id} would be evaluated but is not a gate"

    def test_locked_rules_store_nothing_and_editable_rules_do(self) -> None:
        """A locked invariant with a field would imply a toggle exists somewhere; an editable
        rule without one has nowhere to put the operator's choice."""
        for rule in RULES:
            if rule.control.kind is ControlKind.LOCKED:
                assert not rule.field_name, f"{rule.id} is locked but reads a stored field"
            else:
                assert rule.field_name, f"{rule.id} is editable but names no field"

    def test_every_locked_invariant_says_where_it_is_enforced(self) -> None:
        """"Locked on" is a claim. It has to point somewhere."""
        for rule in RULES:
            if rule.enforcement is Enforcement.ELSEWHERE:
                assert rule.enforced_by, f"{rule.id} claims enforcement without naming it"

    def test_every_rule_lands_in_a_group_the_ui_renders(self) -> None:
        """A rule whose tag has no group title is invisible in the UI — a setting that
        exists, is enforced, and cannot be found."""
        known = {tag for tag, _ in TAG_TITLES}
        for rule in RULES:
            assert rule.tags, f"{rule.id} has no tag"
            assert set(rule.tags) <= known, f"{rule.id} has a tag with no group title"

    @pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
    def test_every_rule_explains_itself(self, rule) -> None:  # type: ignore[no-untyped-def]
        """The rationale is shown next to the control. An operator raising a cap deserves to
        know what it was protecting them from."""
        assert len(rule.rationale) > 40
        assert rule.title
        assert rule.clause


class TestControlBoundsMatchTheModel:
    """A control offering a value Pydantic rejects produces a 422 the operator cannot act on.

    Only the numeric kinds are checked; the others have no bound to compare.
    """

    _NUMERIC: ClassVar[set[ControlKind]] = {
        ControlKind.INTEGER,
        ControlKind.PERCENT,
        ControlKind.MONEY_K,
        ControlKind.DAYS,
        ControlKind.SECONDS,
    }

    def test_maximum_offered_value_is_accepted_by_the_model(self) -> None:
        for rule in RULES:
            if rule.control.kind not in self._NUMERIC or rule.control.max is None:
                continue
            value = rule.control.max
            if rule.control.kind is ControlKind.PERCENT:
                value = value / 100  # the control is 0-95, the field is 0-1
            AutomationPolicy(**{rule.field_name: value})  # must not raise

    def test_minimum_offered_value_is_accepted_by_the_model(self) -> None:
        for rule in RULES:
            if rule.control.kind not in self._NUMERIC or rule.control.min is None:
                continue
            AutomationPolicy(**{rule.field_name: rule.control.min})
