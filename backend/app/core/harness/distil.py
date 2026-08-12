"""Skill distiller: turn a run trajectory into durable, shareable site knowledge.

Asks the LLM "what would let us do this in 1-3 steps next time?" and returns a candidate
skill. The caller PII-gates and stores it (``skills.record_skill``). LLM injected for tests.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel

_DISTIL_SYSTEM = (
    "You distill durable, reusable knowledge about a website from an automation run — the "
    "stable map of the site (selectors, URL patterns, hidden waits, traps), NOT a narration "
    "of this specific task and NEVER any personal data, credentials, emails, or tokens. "
    "If there is nothing durable worth saving, set worth_saving=false."
)


class DistilledSkill(BaseModel):
    worth_saving: bool = False
    content: str = ""


class _StructuredLLM(Protocol):
    async def complete_with_structured_output(
        self, *, prompt: str, output_schema: type[BaseModel], system_prompt: str, purpose: str
    ) -> Any: ...


async def distil_skill(llm: _StructuredLLM, domain: str, summary: dict) -> DistilledSkill:
    """Propose a durable domain skill from a run trajectory (PII-gated by the caller)."""
    prompt = (
        f"Review this automation run on '{domain}'. What durable site knowledge would let us "
        "complete it in 1-3 steps next time? Trajectory summary:\n"
        f"{json.dumps(summary, default=str)[:4000]}\n\n"
        "Return worth_saving and the skill content (markdown). Exclude all personal data."
    )
    result = await llm.complete_with_structured_output(
        prompt=prompt,
        output_schema=DistilledSkill,
        system_prompt=_DISTIL_SYSTEM,
        purpose="skill_distill",
    )
    return result if isinstance(result, DistilledSkill) else DistilledSkill.model_validate(result)
