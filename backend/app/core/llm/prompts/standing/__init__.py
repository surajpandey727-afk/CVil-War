"""Standing instructions from the product owner that every résumé-related LLM call must follow.

Two briefs, each stored verbatim in its own module:

* ``ATS_EVALUATION_STANDARD`` — how a résumé is to be scored and judged against a job.
* ``RESUME_GENERATION_STANDARD`` — how the final job-tailored résumé is to be produced.

``with_standing`` puts them in front of a call's own system prompt. The briefs are the owner's
words and come first, unaltered; what follows them is the call-specific task and output format.
"""

from app.core.llm.prompts.standing.ats_evaluation_standard import ATS_EVALUATION_STANDARD
from app.core.llm.prompts.standing.resume_generation_standard import RESUME_GENERATION_STANDARD

_HEADER = (
    "STANDING INSTRUCTIONS FROM THE PRODUCT OWNER — FOLLOW THESE ON EVERY CALL, WORD FOR WORD.\n"
    "They are reproduced exactly as written. The task for THIS call, and the output format it "
    "requires, follow after them."
)

_RUNTIME_NOTE = (
    "HOW THESE INSTRUCTIONS APPLY IN THIS CALL.\n"
    "You are one step inside CVil-War's pipeline. The pipeline itself reads and edits the "
    "candidate's PDF, reparses the final file, scores it, and runs the claim, language, layout "
    "and pagination validators; you cannot and must not produce a PDF, prose report or anything "
    "other than what this call's task below asks for. Apply every standing instruction that "
    "concerns your step — evidence, truthfulness, wording, scoring honesty, what to change and "
    "what not to — and return ONLY the structured output the task specifies. Where a standing "
    "instruction describes work done by another step, do not attempt it here and do not claim "
    "it has been done. Never trade accuracy for a higher number: where an instruction here "
    "conflicts with the task's own factual limits (evidence, line capacity), the factual limit "
    "wins and the shortfall is reported, not hidden. Where the standards call for improving "
    "weak wording, surfacing supported evidence or sharpening keyword alignment, do it: "
    "returning a line with its original wording is not an edit and is discarded."
)


def with_standing(task_prompt: str, *standards: str) -> str:
    """``standards`` (verbatim), then the runtime note, then ``task_prompt``."""
    body = "\n\n=====\n\n".join(s.strip() for s in standards)
    return f"{_HEADER}\n\n{body}\n\n=====\n\n{_RUNTIME_NOTE}\n\n=====\n\n{task_prompt}"


__all__ = ["ATS_EVALUATION_STANDARD", "RESUME_GENERATION_STANDARD", "with_standing"]
