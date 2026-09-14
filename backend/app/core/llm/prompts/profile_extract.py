"""Structured candidate-profile extraction from an uploaded résumé.

The multi-factor ATS score has always needed real work-history/education data to score
against (see ``services.resume._experience_entries_for_scoring``); without it, two of its
three factors are a flat neutral default for every job. Nothing in the product previously
turned an uploaded résumé's own text into that stored profile — the operator had to
hand-retype their entire work history into Settings before scoring meant anything. This
prompt does that conversion once, from a résumé they already uploaded.
"""

PROFILE_EXTRACT_SYSTEM_PROMPT = """\
You extract structured career data from a résumé's raw text. \
Read only what is actually written — never invent a job, employer, date, or degree that \
is not in the text. If a field is not stated, leave it blank rather than guessing. \
Dates should be copied in whatever format the résumé itself uses (e.g. "Jan 2021", \
"2021", "2021-06"); use "Present" for an ongoing role's end date. \
Return ONLY valid JSON matching the required schema."""


def render_profile_extract_prompt(resume_text: str) -> str:
    """Build the user prompt for one résumé's structured extraction.

    Args:
        resume_text: The résumé's full parsed text.

    Returns:
        The prompt string.
    """
    return (
        "Extract this candidate's work experience and education from the résumé text "
        "below. For each role, include the job title, employer, start date, end date "
        "(or \"Present\"), and a short description. For each qualification, include the "
        "degree, institution, and graduation year.\n\n"
        f"RÉSUMÉ TEXT:\n{resume_text[:12000]}"
    )
