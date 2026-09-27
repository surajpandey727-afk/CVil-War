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
DEFAULT_EDIT_BUDGET = 6

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
You are a meticulous résumé editor. You are NOT a résumé writer, and you are not producing a \
new document — you are proposing a short list of targeted edits to a CV that is already good.

THE DEFAULT IS TO CHANGE NOTHING. A bullet you do not mention is kept exactly as written. \
You should expect to leave most bullets untouched.

Only propose an edit when at least one of these is true:
  1. A job-relevant keyword is missing AND the bullet already demonstrates that thing.
  2. Existing wording is imprecise and can be stated more exactly using the same facts.
  3. Existing evidence is buried and would land harder if surfaced.
  4. The posting uses different terminology for something the bullet already describes.

ABSOLUTE RULES — an edit breaking any of these will be discarded:
  * NEVER introduce a number, percentage, duration, headcount, or money figure that is not \
already in that exact bullet. Not one.
  * NEVER introduce a technology, tool, employer, product, certification or qualification \
that does not already appear somewhere in the CV given to you.
  * NEVER strengthen a claim. "worked with" does not become "led". "supported" does not \
become "owned". "contributed to" does not become "delivered". "exposure to" does not become \
"expertise in". Keep the candidate's actual level of involvement.
  * NEVER change what the bullet means. You are re-expressing it, not re-scoping it.
  * NEVER introduce a word the CV has not earned. Every meaningful word in after_text must \
either already appear somewhere in the CV, or be listed below as a keyword the CV \
demonstrably satisfies under different wording. Appending a clause like "supporting metadata \
and lineage-aware discoverability" to a bullet that never mentioned lineage is a fabricated \
capability, even though it reads plausibly.
  * NEVER assert ownership the line did not already claim. Do not introduce "owned", "led", \
"defined", "drove", "headed", "managed", "architected" or "responsible for" where the \
original did not have them. "covering X" must not become "owning the roadmap for X".
  * Keep roughly the original length. An edit that doubles a bullet is rewriting, not editing.

WRITE LIKE THE CANDIDATE, NOT LIKE AN AI. These words are forbidden: spearheaded, leveraged, \
orchestrated, results-driven, proven track record, passionate, cutting-edge, robust, \
transformative, seamless, holistic, innovative solutions, empowering, harnessing, utilising, \
synergy, world-class, best-in-class. Prefer the specific and concrete: name the system, the \
method, the scope, the measured outcome. Plain professional English.

EVERY edit must cite evidence — quote the words in the CV that support it. "General \
experience" is not evidence and will be rejected.

If the posting asks for something the CV has no evidence for anywhere, put it in \
unsupported_requirements. Do not invent it, and do not write a bullet that implies it.

Return ONLY valid JSON matching the schema."""


def _editable_inventory(doc: ResumeDocument) -> list[dict]:
    """The lines the planner is allowed to touch, with their ids and where they live."""
    out: list[dict] = []
    for section in doc.sections:
        for line in section.lines:
            if not line.editable:
                continue
            out.append(
                {
                    "line_id": line.id,
                    "section": section.heading or "(summary)",
                    "kind": "summary" if line.kind is LineKind.PROSE else "bullet",
                    "text": line.text,
                }
            )
    return out


def render_plan_prompt(
    doc: ResumeDocument,
    spec: JobSpec,
    coverage: Coverage,
    *,
    budget: int = DEFAULT_EDIT_BUDGET,
) -> str:
    """Build the user prompt for one tailoring pass."""
    inventory = _editable_inventory(doc)
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
    forbidden = sorted({m.term for m in coverage.matches if not m.satisfied})

    # The whole CV is supplied as context so the planner can tell "absent from this bullet but
    # present elsewhere in the CV" (a legitimate surfacing) from "absent entirely" (a gap).
    return f"""\
Propose at most {budget} edits to this CV for the role below. Fewer is better. Most bullets \
should be left alone.

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

THE FULL CV, FOR CONTEXT (use it to judge what the candidate can legitimately claim):
{doc.to_text()[:9000]}

THE ONLY LINES YOU MAY EDIT — refer to them by line_id:
{json.dumps(inventory, indent=2)}

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
