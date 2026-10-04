"""Decide the smallest set of edits that make a CV land for one posting.

The engine this replaces told the model to "rewrite the professional summary" and to "rewrite
the bullet points" in *each* experience entry — unconditionally, with no notion of leaving
something alone. Every bullet came back reworded whether or not the rewording helped, which
is why the output stopped sounding like the person who wrote it.

Here the default is KEEP and an edit has to earn its place. The planner is handed the bullets
with stable ids and asked for a short list of changes; anything it does not name is emitted
verbatim. That inverts the previous behaviour: silence preserves, rather than silence being
impossible.

Nothing this module returns is trusted. The prompt states the rules, the validator enforces
them, and an edit that fails enforcement is dropped while the rest of the plan proceeds — a
single bad suggestion costs one bullet, not the whole tailoring pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field

from app.core.llm.prompts.sanitize import wrap_untrusted
from app.core.resume_tailoring.evidence import MISSING, Coverage
from app.core.resume_tailoring.jobspec import JobSpec, Tier
from app.core.resume_tailoring.model import LineKind, ResumeDocument


class Action(StrEnum):
    """What to do with one editable line."""

    KEEP = "keep"
    #: Same facts, sharper wording or a supported keyword worked in.
    TWEAK = "tweak"
    #: Move within its own section. No wording change.
    REORDER = "reorder"


class EditLevel(StrEnum):
    """How far an edit goes, per the house rules.

    Level 5 has no member. A fabricated claim is not a level of editing the system supports,
    so it is not representable here and the validator rejects anything that looks like one.
    """

    NONE = "0_no_change"
    CLARITY = "1_clarity"
    STRONGER_WORDING = "2_stronger_wording"
    POSITIONING = "3_positioning"
    KEYWORD_ALIGNMENT = "4_keyword_alignment"


class ProposedEdit(BaseModel):
    """One change the planner wants to make."""

    line_id: str = ""
    action: str = Action.KEEP.value
    after_text: str = ""
    reason: str = ""
    #: Must name the CV content that supports the change. Vague evidence is rejected.
    evidence: str = ""
    keywords_added: list[str] = Field(default_factory=list)
    level: str = EditLevel.CLARITY.value


class BulletOrder(BaseModel):
    """A new order for the bullets inside one section."""

    section_heading: str = ""
    line_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class EditPlan(BaseModel):
    """The planner's whole answer."""

    edits: list[ProposedEdit] = Field(default_factory=list)
    reorder: list[BulletOrder] = Field(default_factory=list)
    #: Requirements the planner could find no evidence for. Surfaced, never papered over.
    unsupported_requirements: list[str] = Field(default_factory=list)
    positioning_note: str = ""


#: Ceiling on edits per pass. A CV of twenty-odd bullets does not need twenty-odd rewrites,
#: and a small budget forces the planner to spend it on the bullets that actually matter.
DEFAULT_EDIT_BUDGET = 14

#: Wording that marks a résumé as machine-written. Listed in the prompt and enforced by the
#: validator, because stating a ban has never been sufficient on its own.
BANNED_PHRASES: tuple[str, ...] = (
    "spearheaded", "leveraged", "leveraging", "drove strategic initiatives",
    "played a pivotal role", "dynamic professional", "results-driven", "results driven",
    "proven track record", "passionate", "cutting-edge", "cutting edge", "robust",
    "transformative", "synergised", "synergized", "synergy", "revolutionised",
    "revolutionized", "orchestrated", "holistic", "seamless", "seamlessly",
    "innovative solutions", "unlocking", "empowering", "harnessing", "utilising",
    "utilizing", "utilise", "utilize", "best-in-class", "world-class", "game-changing",
    "thought leader", "deep dive", "move the needle", "value-add", "spearhead",
)


SYSTEM_PROMPT = """\
You are the résumé editor inside a production pipeline. You propose targeted edits to lines of \
the candidate's CV so that the final PDF represents the strongest truthful version of them for \
ONE job posting. The owner's standing instructions above govern, including the addendum: a CV \
is a curated selection, not an inventory, and "not on this CV" never means "not done".

WHAT YOU MAY USE AS EVIDENCE. Three sources, and only these:
  1. The CV itself.
  2. TRUSTED CAREER EVIDENCE supplied in the prompt: the career profile, the candidate's other \
résumés, and the OWNER-DECLARED EXPERIENCE list (capabilities the owner states they worked with \
or on in the last three years).
  3. Reasonable inference from the work a bullet already describes: a bullet about a deployed \
model supports "productionisation"; a bullet about a dashboard supports "data visualisation" \
and "BI"; a bullet about requirements supports "requirements engineering".
Finance-related technology is the one area the owner did NOT work in: never write a finance, \
banking, payments, trading or accounting capability, whatever the posting asks.

WHAT TO DO. Be aggressive about covering the posting. For each requirement that is not \
evidenced strongly, find the line whose work could genuinely have involved it and say so in the \
posting's own terminology (and a synonym where it helps), surfacing declared capabilities into \
the bullets, the summary and the skills rows. Rewrite weak bullets properly: action + technical \
capability + context + scale + outcome. Lead with what matters for THIS role. Prefer editing \
the lines where the posting's priorities sit. Cut filler and generic soft-skill wording while \
you are there. Keep the candidate's level of involvement: do not turn "supported" into "led".

ABSOLUTE RULES — an edit breaking any of these is discarded by code:
  * NEVER introduce a number, percentage, duration, headcount or money figure the bullet does \
not already contain, unless a trusted source states it for this same work. Metrics are never \
invented.
  * NEVER invent an employer, a project, a certification, a qualification, a date or a title.
  * NEVER introduce a technology or capability that appears in none of the three sources above.
  * NEVER assert ownership or leadership (owned, led, defined, drove, managed, architected, \
responsible for) that the line did not already claim.
  * NEVER write a finance-domain capability.
  * A skills row (kind "skills_row") keeps its label and every existing item in order; you may \
only append items, and only declared or already-evidenced ones, within max_chars.
  * An edit must fit its line's max_chars; one that does not is discarded.

WRITE LIKE A HUMAN, NOT LIKE AN AI. Forbidden words: spearheaded, leveraged, orchestrated, \
results-driven, proven track record, passionate, cutting-edge, robust, transformative, \
seamless, holistic, innovative solutions, empowering, harnessing, utilising, synergy, \
world-class, best-in-class. No keyword stuffing, no repeated bullets, no adjectives that carry \
no information. Plain, specific, professional English.

EVERY edit must cite evidence. Quote the CV words that support it; where the capability comes \
from a trusted source, name that source in square brackets, e.g. "[Owner-declared experience \
(standing brief)] Power BI". "General experience" is not evidence and will be rejected.

If the posting asks for something none of the sources can support, put it in \
unsupported_requirements. Do not write a line that implies it.

Return ONLY valid JSON matching the schema."""


def _editable_inventory(doc: ResumeDocument, exclude: frozenset[str] = frozenset()) -> list[dict]:
    """The lines the planner is allowed to touch, with their ids and where they live."""
    out: list[dict] = []
    for section in doc.sections:
        for line in section.lines:
            if not line.editable or line.id in exclude:
                continue
            entry = {
                "line_id": line.id,
                "section": section.heading or "(summary)",
                "kind": {LineKind.PROSE: "summary", LineKind.SKILL: "skills_row"}.get(line.kind, "bullet"),
                "text": line.text,
            }
            # On a PDF the edit is written back into the page, so a line has a hard capacity.
            if line.id in doc.capacity:
                entry["max_chars"] = doc.capacity[line.id]
            out.append(entry)
    return out


def render_plan_prompt(
    doc: ResumeDocument,
    spec: JobSpec,
    coverage: Coverage,
    *,
    budget: int = DEFAULT_EDIT_BUDGET,
    trusted: tuple = (),
    exclude: frozenset[str] = frozenset(),
    focus: tuple[str, ...] = (),
) -> str:
    """Build the user prompt for one tailoring pass.

    ``trusted`` is trusted career evidence beyond this CV (see ``trusted.TrustedSource``).
    ``exclude`` lists lines an earlier round already edited; they are not offered again.
    ``focus`` names requirements the CV evidences only weakly (listed, or under other wording),
    which a further round should try to show where a bullet genuinely does that work.
    """
    inventory = _editable_inventory(doc, exclude)
    mandatory_missing = [
        m.term for m in coverage.matches if m.kind == MISSING and m.tier is Tier.MANDATORY
    ]
    # Terms the matcher confirmed the CV satisfies under other wording. These are the only
    # words an edit may introduce that the CV does not already contain, so the planner is
    # told about them explicitly rather than guessing and having the edit thrown out.
    allowed_wording = sorted({m.term for m in coverage.matches if m.satisfied})
    # Naming the forbidden terms outright works far better than hoping the planner infers
    # them from their absence: left to itself it reached for "lineage", "discoverability",
    # "roadmap" and "regulatory" on every attempt, and every one of those edits was thrown
    # out downstream. Telling it up front turns five wasted proposals into usable ones.
    trusted_text = chr(10).join(f"[{t.label}]{chr(10)}{t.text}" for t in trusted)
    lowered = trusted_text.lower()
    # A term the CV lacks but a trusted source states is not forbidden: it is a fact the CV left
    # out, and may be surfaced where a bullet already concerns it.
    recoverable = sorted(
        {m.term for m in coverage.matches if not m.satisfied and m.term.lower() in lowered}
    )
    forbidden = sorted(
        {m.term for m in coverage.matches if not m.satisfied and m.term.lower() not in lowered}
    )
    evidence_block = (
        f"""
TRUSTED CAREER EVIDENCE — what the candidate's own records and the owner's standing declaration say they did, beyond what this CV prints. A fact from here may be surfaced in an edit where it belongs to that line's work, and the edit's "evidence" must then name the source in square brackets (for example "[Owner-declared experience (standing brief)] Power BI"). Nothing outside this block or the CV may be written.
{trusted_text[:12000]}

TERMS THE POSTING WANTS THAT ONLY THIS EVIDENCE SUPPORTS — recoverable, where a bullet fits:
{json.dumps(recoverable, indent=2)}
"""
        if trusted_text
        else ""
    )

    focus_block = (
        f"""
FOCUS FOR THIS ROUND — the CV evidences these requirements weakly or not at all (listed as a
skill, described in other words, or left out). Where a bullet below performs that work, show it in
the posting's own terms and in context (what you did with it, at what scale, to what end), not as
a bare keyword. Where the TRUSTED CAREER EVIDENCE states the capability but no bullet shows it,
write it into the bullet whose work it fits, or append it to the matching skills row. Never attach
a capability to a line whose work it cannot belong to, and never write a finance-domain term:
{json.dumps(list(focus), indent=2)}
"""
        if focus
        else ""
    )

    # The whole CV is supplied as context so the planner can tell "absent from this bullet but
    # present elsewhere in the CV" (a legitimate surfacing) from "absent entirely" (a gap).
    return f"""\
Propose up to {budget} edits to this CV for the role below: the changes that give the \
strongest, most defensible match to this posting. Each edit must genuinely change its line. A line you keep must be \
omitted from the list, not repeated back.

TARGET ROLE: {spec.title or "(untitled)"}

{wrap_untrusted(spec.raw_text[:8000], label="JOB POSTING")}

TERMS YOU MUST NOT WRITE. The posting asks for these and this CV evidences none of them
anywhere. Using one would be a fabricated capability, and the edit will be discarded:
{json.dumps(forbidden, indent=2)}

KEYWORDS YOU MAY WRITE EVEN THOUGH THE CV USES DIFFERENT WORDS FOR THEM — these have already
been verified against the CV's own evidence, so using the posting's wording for them is
accurate, not a new claim:
{json.dumps(allowed_wording, indent=2)}

OF THOSE, THESE ARE MANDATORY FOR THE ROLE:
{json.dumps(mandatory_missing, indent=2)}

{evidence_block}{focus_block}
THE FULL CV, FOR CONTEXT (use it to judge what the candidate can legitimately claim):
{doc.to_text()[:9000]}

THE ONLY LINES YOU MAY EDIT — refer to them by line_id:
{json.dumps(inventory, indent=2)}

Where a line has "max_chars", the edited line is written back onto the original page and cannot be longer than that. Stay within it; an edit that does not fit is discarded.

For each edit return: line_id, action ("tweak"), after_text, reason, evidence (quote the CV), \
keywords_added, and level (one of "1_clarity", "2_stronger_wording", "3_positioning", \
"4_keyword_alignment").

after_text MUST be the COMPLETE replacement for that line — the whole sentence or bullet, \
start to finish, with your change worked into it. It is substituted for the entire line. Do \
NOT return only the phrase you changed, a fragment, or a description of the change; an \
after_text shorter than the line it replaces will be discarded as a truncation.

You may also return `reorder`: for a section, the line_ids of its bullets in a better order \
for this role. Reordering changes no wording and is often the highest-value, lowest-risk move \
available — prefer it where the CV already contains the right evidence in the wrong place.

List anything the posting needs that this CV genuinely cannot evidence in \
unsupported_requirements."""


@dataclass
class PlanContext:
    """What the caller needs to keep alongside a plan."""

    doc: ResumeDocument
    spec: JobSpec
    coverage: Coverage
    budget: int = DEFAULT_EDIT_BUDGET
    notes: list[str] = field(default_factory=list)
