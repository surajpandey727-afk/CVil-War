"""The owner's two standing briefs must reach every résumé LLM call, unaltered."""

from __future__ import annotations

import pytest

from app.core.llm.prompts.standing import (
    ATS_EVALUATION_STANDARD,
    RESUME_GENERATION_STANDARD,
    with_standing,
)
from app.core.resume_tailoring.engine import tailor
from app.core.resume_tailoring.extract import parse_resume_text
from app.core.resume_tailoring.plan import EditPlan

#: Sentences from the briefs that identify them and that no paraphrase would preserve exactly.
ATS_MARKERS = [
    "# TASK: BUILD A REALISTIC ATS + RESUME SHORTLISTING EVALUATION ENGINE",
    "Do NOT give me inflated scores to make the product look successful.",
    "A score of 72 is better than a fake 92.",
    "Requirement Coverage              25%",
    "Do not optimise for a high number.",
    "\"Exactly how competitive is this resume for THIS job, what evidence supports that assessment, what is missing, and what specific changes would improve it without fabricating anything?\"",
]
GENERATION_MARKERS = [
    "FINAL PRODUCTION TASK — GENERATE THE ACTUAL FINAL JOB TAILORED RESUME PDF",
    "LEVEL 7 and LEVEL 8 MUST NEVER ENTER THE FINAL RESUME.",
    "THE FIRST HORIZONTAL SEPARATOR IN THIS RESUME MUST END ON PAGE 1.",
    "`EXTRA-CURRICULAR EXPERIENCE` MUST START ON A NEW PAGE.",
    "Minimum acceptable:\n82",
    "Keep looping until the final PDF is genuinely ready to submit.",
]


@pytest.mark.parametrize("marker", ATS_MARKERS)
def test_the_ats_brief_is_stored_verbatim(marker):
    assert marker in ATS_EVALUATION_STANDARD


@pytest.mark.parametrize("marker", GENERATION_MARKERS)
def test_the_generation_brief_is_stored_verbatim(marker):
    assert marker in RESUME_GENERATION_STANDARD


def test_the_composer_puts_the_briefs_first_and_unaltered_before_the_task():
    prompt = with_standing("TASK-SPECIFIC INSTRUCTIONS", RESUME_GENERATION_STANDARD, ATS_EVALUATION_STANDARD)
    assert RESUME_GENERATION_STANDARD.strip() in prompt and ATS_EVALUATION_STANDARD.strip() in prompt
    assert prompt.index(RESUME_GENERATION_STANDARD.strip()) < prompt.index("TASK-SPECIFIC INSTRUCTIONS")
    assert prompt.endswith("TASK-SPECIFIC INSTRUCTIONS")


async def test_the_tailoring_engine_sends_both_briefs_to_the_model():
    seen = {}

    class Capture:
        async def complete_with_structured_output(self, *, system_prompt, **_):
            seen["system"] = system_prompt
            return EditPlan()

    doc = parse_resume_text("Name\nemail@example.com\n\nEXPERIENCE\n- Built a Python forecasting model for retail demand.")
    await tailor(doc, "Data Scientist. Python and forecasting.", job_title="Data Scientist", llm=Capture())

    assert RESUME_GENERATION_STANDARD.strip() in seen["system"]
    assert ATS_EVALUATION_STANDARD.strip() in seen["system"]
    assert "You are the résumé editor inside a production pipeline" in seen["system"], "the call's own task must still follow"
