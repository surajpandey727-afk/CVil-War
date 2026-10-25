"""The application pack: everything needed to apply by hand, ready to copy.

Not every vacancy can be submitted automatically (live apply off, a portal that needs a login,
a form the agent cannot read). Dreamwork's answer, adopted here: the application is still
prepared — the employer link, the CV to attach, the cover letter, and answers to the questions
UK application forms nearly always ask — so applying by hand takes minutes.

The owner's experience policy governs every answer. An answer is ``supported`` only when it is
the candidate's own stored data or a verbatim line of their CV; anything the system cannot
know (right to work, sponsorship, notice period, salary) is an explicit placeholder marked
``add_only_if_true``, never a guess. The one composed answer ("why this role") is built only
from résumé evidence and then re-graded by the same guard the Résumé checker uses.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.resume_check.suggest import evidence_status
from app.schemas.resume_check import ResumeCheckResponse

PLACEHOLDER = "[Add only if true]"


@dataclass(frozen=True)
class Answer:
    question: str
    answer: str
    evidence_status: str  # supported | add_only_if_true
    note: str = ""


def _from_profile(question: str, value: str | None, *, note: str = "") -> Answer:
    if value and value.strip():
        return Answer(question, value.strip(), "supported", note)
    return Answer(question, PLACEHOLDER, "add_only_if_true", note or "Not in your profile yet.")


def build_answers(
    *,
    profile: dict,
    resume_text: str,
    job_title: str,
    company: str,
    check: ResumeCheckResponse | None,
) -> list[Answer]:
    """Answers to the questions UK application forms commonly ask, under the evidence policy."""
    answers = [
        _from_profile("Full name", profile.get("full_name")),
        _from_profile("Email", profile.get("email")),
        _from_profile("Phone", profile.get("phone")),
        _from_profile("Location", profile.get("location")),
        _from_profile("LinkedIn profile", profile.get("linkedin_url")),
        Answer(
            "Do you have the right to work in the UK?",
            PLACEHOLDER,
            "add_only_if_true",
            "Only you can answer this; it is never inferred.",
        ),
        Answer(
            "Will you now or in the future require visa sponsorship?",
            PLACEHOLDER,
            "add_only_if_true",
            "Answer exactly as your visa status stands today.",
        ),
        Answer("What is your notice period?", PLACEHOLDER, "add_only_if_true"),
        Answer(
            "What are your salary expectations?",
            PLACEHOLDER,
            "add_only_if_true",
            "Check the posting's range first if it lists one.",
        ),
    ]
    summary = (profile.get("summary") or "").strip()
    if summary:
        answers.append(
            Answer(
                "Summarise your relevant experience",
                summary,
                evidence_status(summary, resume_text + "\n" + summary),
            )
        )
    why = _why_this_role(job_title, company, check)
    if why:
        answers.append(
            Answer(
                f"Why do you want to work at {company or 'this company'}?",
                why,
                evidence_status(why, f"{resume_text}\n{job_title}\n{company}"),
                "Drafted only from lines in your CV. Add what genuinely draws you to them.",
            )
        )
    return answers


def _why_this_role(title: str, company: str, check: ResumeCheckResponse | None) -> str:
    if check is None:
        return ""
    musts = [m for m in check.matched_skills if m.must_have and m.evidence]
    if not musts:
        return ""
    skills = ", ".join(m.label.lower() for m in musts[:3])
    quote = musts[0].evidence[0].quote.rstrip(".")
    return (
        f"The {title} role centres on {skills}, which is where my experience is strongest — "
        f"for example: {quote}. [Add what specifically draws you to {company or 'the company'}.]"
    )


def checklist(*, has_cv: bool, has_cover_letter: bool, url: str | None) -> list[str]:
    items = []
    if url:
        items.append("Open the employer's application page (link above).")
    items.append(
        "Attach the CV shown above." if has_cv else "Attach a CV — none is linked to this yet."
    )
    if has_cover_letter:
        items.append("Attach or paste the cover letter.")
    items.append("Copy the answers below; replace every [Add only if true] with your real answer.")
    items.append("Mark the application as applied here once it is sent, so tracking stays honest.")
    return items
