"""Recovering JSON from a model reply that ignored ``response_format``.

Every shape here was either observed against the live gateway or is the obvious neighbour of
one. The client asks for JSON three ways — schema injection, an explicit instruction, and
``response_format={"type":"json_object"}`` — and the model still returned a prose preamble
followed by a markdown table. 12k tokens were spent and the parse discarded all of it.
"""

from __future__ import annotations

import json

import pytest

from app.core.llm.json_salvage import extract_json


class TestCleanInput:
    def test_a_bare_object_is_returned_unchanged(self) -> None:
        assert extract_json('{"a": 1}') == '{"a": 1}'

    def test_surrounding_whitespace_is_stripped(self) -> None:
        assert extract_json('\n  {"a": 1}  \n') == '{"a": 1}'

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_empty_input_is_passed_through(self, value) -> None:  # type: ignore[no-untyped-def]
        assert extract_json(value) == ""


class TestFencedBlocks:
    def test_a_json_fence_is_unwrapped(self) -> None:
        content = 'Here you go:\n```json\n{"matches": []}\n```\nHope that helps.'
        assert json.loads(extract_json(content)) == {"matches": []}

    def test_an_unlabelled_fence_is_unwrapped(self) -> None:
        assert json.loads(extract_json('```\n{"a": 1}\n```')) == {"a": 1}

    def test_a_fence_containing_prose_is_skipped_for_the_real_object(self) -> None:
        content = '```\nnot json at all\n```\n\n```json\n{"a": 2}\n```'
        assert json.loads(extract_json(content)) == {"a": 2}


class TestProseWrappedObjects:
    def test_a_preamble_before_the_object_is_dropped(self) -> None:
        """The exact failure observed: the model explains itself first."""
        content = (
            "Based only on the CV text provided, I treated the posting's requirements as "
            'follows.\n\n{"matches": [{"requirement": "Python", "level": "strong"}]}'
        )
        parsed = json.loads(extract_json(content))
        assert parsed["matches"][0]["requirement"] == "Python"

    def test_trailing_commentary_is_dropped(self) -> None:
        content = '{"a": 1}\n\nLet me know if you would like this in another format.'
        assert json.loads(extract_json(content)) == {"a": 1}

    def test_nested_objects_are_balanced_correctly(self) -> None:
        content = 'Result:\n{"outer": {"inner": {"deep": [1, 2]}}, "n": 3}\nDone.'
        assert json.loads(extract_json(content))["outer"]["inner"]["deep"] == [1, 2]

    def test_a_brace_inside_a_string_does_not_end_the_object_early(self) -> None:
        """CV evidence routinely contains braces and quotes. Counting braces naively would
        truncate the object mid-value and produce a parse error on valid output."""
        content = 'Here: {"evidence": "used {braces} and \\"quotes\\" in the CV", "ok": true}'
        parsed = json.loads(extract_json(content))
        assert parsed["evidence"] == 'used {braces} and "quotes" in the CV'
        assert parsed["ok"] is True

    def test_an_escaped_backslash_before_a_quote_is_handled(self) -> None:
        content = r'{"path": "C:\\Users\\", "n": 1}'
        assert json.loads(extract_json(content))["n"] == 1


class TestNoObjectPresent:
    def test_a_markdown_table_yields_no_json_and_still_fails_to_parse(self) -> None:
        """The reply that started this. There is nothing to salvage, and inventing something
        would be worse — the caller falls back to its deterministic path instead."""
        content = (
            "| Requirement | CV evidence |\n|---|---|\n"
            "| Python | Pandas, NumPy |\n| Kubernetes | missing |"
        )
        with pytest.raises(json.JSONDecodeError):
            json.loads(extract_json(content))

    def test_plain_prose_is_returned_unchanged_for_the_caller_to_reject(self) -> None:
        assert extract_json("I cannot help with that.") == "I cannot help with that."

    def test_an_unbalanced_object_is_not_repaired(self) -> None:
        """Truncated output must fail, not be guessed at. Acting on half a report is worse
        than falling back to keyword matching."""
        with pytest.raises(json.JSONDecodeError):
            json.loads(extract_json('{"a": 1, "b": {'))
