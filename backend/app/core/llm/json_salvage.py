"""Recover a JSON object from a model reply that did not honour ``response_format``.

The client already asks for JSON three ways: it injects the schema, it says "respond ONLY
with the JSON object", and it sets ``response_format={"type": "json_object"}``. Against the
gateway this deployment runs, the model still replied with a prose preamble and a markdown
comparison table — the request succeeded, 12k tokens were spent and billed, and the parse
then threw the whole thing away.

Asking harder is not a fix, because ``response_format`` is a gateway capability and this
gateway does not enforce it. So the parse is made tolerant of the shapes a model actually
emits: a fenced block, a JSON object with prose wrapped around it, or clean JSON.

Deliberately narrow. This finds a *syntactically balanced* object and hands it to
``json.loads``; it never repairs malformed JSON, and a reply with no object in it at all
still fails, which is correct — the caller then falls back to its deterministic path rather
than acting on something reconstructed from a table.
"""

from __future__ import annotations

import re

#: ```json … ``` or a bare ``` … ``` fence. Models add these even when told not to.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(content: str) -> str:
    """Return the JSON object embedded in ``content``, or the content unchanged.

    Unchanged rather than raising, so the caller's existing error path stays the single place
    that reports a failed parse.
    """
    text = (content or "").strip()
    if not text:
        return text

    # Already clean.
    if text.startswith("{") and text.endswith("}"):
        return text

    # Fenced: take the first block that looks like an object.
    for block in _FENCE.findall(text):
        candidate = block.strip()
        if candidate.startswith("{"):
            return candidate

    # Prose around an object: scan for the first balanced {...}, respecting strings and
    # escapes so a brace inside a quoted value does not end the object early.
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text
