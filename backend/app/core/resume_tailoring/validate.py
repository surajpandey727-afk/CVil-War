"""Enforce the tailoring rules on the planner's output.

The prompt states the rules; this decides whether they were followed. That split matters,
because the previous engine's only defence was prompt text — "NEVER fabricate" with nothing
checking compliance — and the guard that did exist inspected three fields (company,
institution, skill name) while every invented metric and every upgraded verb lived in the
free-text bullets it never looked at.

Checks run per edit and then over the whole document. A per-edit failure drops that one edit
and keeps the rest of the plan; a document-level failure fails the pass, because by then
something structural has moved and shipping it would mean shipping a CV the operator did not
write.
"""
# ruff: noqa: SIM905
# Word lists are written as one space-separated string and split at import. The
# suggested list literal puts sixty quoted words on a single line, which is how a
# 563-character line got into this file in the first place.


from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.resume_tailoring.declared import excluded_terms_added
from app.core.resume_tailoring.model import LineKind, ResumeDocument
from app.core.resume_tailoring.plan import BANNED_PHRASES, ProposedEdit

#: Any figure a bullet can carry: counts, percentages, money, durations, versions.
_NUMBER = re.compile(r"\d[\d,.]*\s*(?:%|k\b|m\b|bn\b|\+)?", re.I)

#: Verb upgrades that change what the candidate actually did. Checked directionally: the
#: weaker word disappearing and a stronger one arriving in the same bullet is an escalation,
#: which is a fabricated claim about seniority even when every noun stays the same.
_ESCALATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("worked with", ("led", "directed", "headed", "managed", "owned")),
    ("supported", ("owned", "led", "drove", "directed", "headed")),
    ("contributed to", ("delivered", "led", "owned", "built", "drove")),
    ("assisted", ("led", "owned", "managed", "delivered")),
    ("helped", ("led", "owned", "delivered", "drove")),
    ("exposure to", ("expertise in", "expert in", "specialised in", "specialized in")),
    ("familiar with", ("expert in", "expertise in", "mastered")),
    ("participated in", ("led", "owned", "ran", "directed")),
    ("collaborated", ("led", "directed", "managed")),
    ("involved in", ("led", "owned", "delivered")),
)

#: Verbs that assert ownership, leadership or authorship. An edit may not introduce one that
#: the original line did not already contain. This is the failure the escalation pairs above
#: miss: "covering API contracts" became "owning the product roadmap for API contracts" — no
#: word was swapped for a listed synonym, no number moved, no technology appeared, and the
#: candidate acquired a roadmap they never claimed.
_OWNERSHIP_VERBS: tuple[str, ...] = (
    "own", "owns", "owned", "owning", "ownership",
    "led", "lead", "leads", "leading", "headed", "heading",
    "drove", "driving", "directed", "directing", "managed", "managing",
    "founded", "established", "launched", "architected", "pioneered", "created",
    "defined", "defining", "authored", "oversaw", "overseeing", "accountable",
    "responsible",
)

#: Words too common to be evidence of anything. A new connective is not a new claim.
#:
#: The second group matters as much as the first. Restricting the check to articles and
#: prepositions rejected edits for introducing "focus", "considerations" and "ensuring" —
#: ordinary English that names no capability, claims no seniority and would not raise a
#: recruiter's eyebrow. Domain nouns are deliberately absent from this list: "lineage",
#: "compliance", "regulatory", "adoption", "roadmap" and "catalogue" each assert something
#: about what the candidate has done, so they stay subject to the evidence check.
_FUNCTION_WORDS = frozenset(
    (
        # grammar
        "a an and or the to of in on for with by at from as is are was were be been being "
        "that this these those it its their our your his her they we you i not no if then "
        "than so such via across into within while during over under about through per each "
        "both all more most other new also including include includes "
        # ordinary verbs and nouns that carry no capability claim
        "focus focused focusing ensure ensures ensuring improve improves improving improved "
        "consideration considerations approach approaches provide provides providing enable "
        "enables enabling help helps helping use uses used using work works working need "
        "needs make makes making better faster safer clearer clear given give gives given "
        "part parts area areas way ways level levels point points case cases item items "
        "based upon onto toward towards between among alongside"
    ).split()
)

#: Evidence strings that assert nothing.
_VAGUE_EVIDENCE = (
    "general experience", "the resume", "the résumé", "the cv", "overall", "various",
    "throughout", "his experience", "their experience", "candidate experience", "n/a",
)

#: Capitalised vocabulary that describes *how work is discussed* rather than a capability the
#: candidate would be claiming to possess. "Defined success criteria" and "defined KPIs" say
#: the same thing about the same work, so re-stating it in the posting's words is the
#: legitimate terminology alignment the rules allow — whereas "Tableau" or "Power BI" is a
#: tool you either used or did not. Anything not on this list still has to be in the CV.
_GENERIC_VOCABULARY = frozenset({
    "kpi", "kpis", "okr", "okrs", "roi", "mvp", "poc", "sla", "slas",
    "ux", "ui", "qa", "eu", "uk", "us",
})

#: How far a bullet may grow or shrink before the edit is a rewrite rather than an edit.
_MAX_LENGTH_RATIO = 1.45
_MIN_LENGTH_RATIO = 0.60
#: Flat allowance that rescues short lines from the ratio test. Forty characters is roughly
#: one clause — enough to name a technology the bullet already implies, not enough to bolt on
#: a new claim.
_MAX_LENGTH_GROWTH = 40

#: Longest run of consecutive new words an edit may insert. Four is enough to work a term
#: into a sentence ("and data platform", "across data pipelines") and not enough to append a
#: capability the bullet never described.
_MAX_INSERT_RUN = 4
#: Total new words across the whole line, so an edit cannot get around the run limit by
#: sprinkling a clause in pieces.
_MAX_INSERT_TOTAL = 8

#: Limits for an edit that draws on trusted evidence beyond the CV (the profile, other résumés, the
#: owner's declared experience). Recovering a capability the CV left out takes more words than
#: re-wording one it has, and the page itself still caps the line's length.
_TRUSTED_INSERT_RUN = 9
_TRUSTED_INSERT_TOTAL = 18
_TRUSTED_LENGTH_RATIO = 1.8
_TRUSTED_LENGTH_GROWTH = 110
#: Most items a skills-row edit may append.
_MAX_SKILL_ITEMS = 6

#: Share of the document's words that must survive a tailoring pass untouched. The owner permits
#: rewriting weak bullets from first principles, so this is a floor against replacing the CV, not
#: against improving it.
MIN_PRESERVED_RATIO = 0.60


@dataclass
class Rejection:
    """One edit that failed, and why."""

    line_id: str
    rule: str
    detail: str


@dataclass
class ValidationReport:
    """What survived, what did not, and whether the pass may ship."""

    accepted: list[ProposedEdit] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    document_failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.document_failures


def _numbers(text: str) -> set[str]:
    return {m.group(0).strip().rstrip("+").replace(",", "") for m in _NUMBER.finditer(text)}


#: A word, keeping internal punctuation that belongs to a name ("ci/cd", "node.js", "c++")
#: while trailing sentence punctuation is stripped afterwards.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+.#/-]*")


def _tokens(text: str) -> set[str]:
    """Normalised words in ``text``, without trailing punctuation.

    Stripping matters: leaving the full stop attached made "platform." a different token from
    "platform", and the technology check then reported a word already in the CV as an
    invention. Three of the first five real edits were rejected for exactly that.
    """
    return {
        m.group(0).strip(".,;:").lower()
        for m in _WORD.finditer(text)
        if m.group(0).strip(".,;:")
    }


def _named_things(text: str) -> set[str]:
    """Tokens that look like a product, tool or technology rather than ordinary prose.

    Two signals, both chosen because they separate "Tableau" and "YOLOv11" from "platform"
    and "ai-generated": a capital letter somewhere other than the start of a sentence, or a
    digit or version symbol inside the word. An ordinary adjective the posting happens to use
    is not a fabricated technology, and flagging it as one blocks perfectly honest edits.
    """
    out: set[str] = set()
    for match in _WORD.finditer(text):
        token = match.group(0).strip(".,;:")
        if len(token) < 2:
            continue
        start = match.start()
        preceding = text[:start].rstrip()
        sentence_start = not preceding or preceding[-1] in ".!?:;\n"
        if (token[0].isupper() and not sentence_start) or re.search(r"[0-9+#]", token):
            out.add(token.lower())
    return out


def _insertions(before: str, after: str) -> tuple[list[int], int]:
    """Sizes of each run of newly inserted words, and their total.

    Measured on words rather than characters because the question is "did this edit add a
    clause?", and a clause is counted in words.
    """
    import difflib

    old_words, new_words = before.split(), after.split()
    runs: list[int] = []
    total = 0
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
        None, old_words, new_words
    ).get_opcodes():
        if tag in ("insert", "replace"):
            added = j2 - j1
            if added > 0:
                runs.append(added)
                total += added
    return runs, total


def _content_words(text: str) -> list[str]:
    """Meaningful words in ``text``: no punctuation, no connectives."""
    return [
        w for w in re.findall(r"[A-Za-z][A-Za-z0-9+#/-]*", text.lower())
        if w not in _FUNCTION_WORDS and len(w) > 2
    ]


def _word_supported(word: str, cv_tokens: set[str], allowed: set[str]) -> bool:
    """Whether the CV entitles the edit to use this word.

    Three ways to qualify, in order of strength: the CV uses the word; the CV uses something
    with the same stem, so "supporting" is earned by "support"; or the word belongs to a
    posting requirement that the evidence matcher independently confirmed the CV satisfies
    under different wording — which is the one case where writing a word the CV never used is
    legitimate, and the reason that check exists at all.
    """
    if word in cv_tokens or word in allowed or word in _GENERIC_VOCABULARY:
        return True
    target = _stem(word)
    return len(target) >= 4 and any(_stem(token) == target for token in cv_tokens)


#: Suffixes stripped before comparing two words. Deliberately small: this exists to relate
#: "applying" to "applied" and "supporting" to "support", not to conflate unrelated words.
_SUFFIXES = ("ingly", "ing", "edly", "ed", "ies", "es", "s", "ment", "tions", "tion")


def _stem(word: str) -> str:
    """A crude stem, enough to match inflections of the same word."""
    out = word
    for suffix in _SUFFIXES:
        if out.endswith(suffix) and len(out) - len(suffix) >= 3:
            out = out[: -len(suffix)]
            break
    # "apply"/"applied" only converge once the y is folded.
    if out.endswith("y"):
        out = out[:-1] + "i"
    return out


def _attributable(number: str, after: str, evidence_text: str) -> bool:
    """Whether a figure the edit introduces is stated, for this same work, in trusted evidence.

    Finding the number somewhere in the evidence is not enough — "70%" appears in a dozen
    places, and attaching it to the wrong bullet is a fabricated result. The evidence line that
    carries the number must also share real subject matter with the sentence it is moving into.
    """
    wanted = set(_content_words(after))
    for line in evidence_text.splitlines():
        if number in _numbers(line) and len(wanted & set(_content_words(line))) >= 3:
            return True
    return False


def check_edit(
    edit: ProposedEdit,
    before: str,
    cv_text: str,
    allowed_terms: frozenset[str] = frozenset(),
    evidence_text: str = "",
    kind: LineKind | None = None,
) -> Rejection | None:
    """Validate one proposed edit against the bullet it changes and the CV as a whole.

    ``evidence_text`` is trusted career evidence beyond this CV (profile, previous résumés).
    A fact the CV omitted may be surfaced from it — the same checks still apply, with the
    evidence counted as part of what the candidate has demonstrably done.

    Returns ``None`` when the edit is acceptable, otherwise the reason it is not.
    """
    after = (edit.after_text or "").strip()
    if not after:
        return Rejection(edit.line_id, "empty", "the edit removes the line entirely")

    low_after = after.lower()
    low_before = before.lower()

    # 0. The one domain the owner did not work in is never claimed.
    finance = excluded_terms_added(before, after)
    if finance:
        return Rejection(
            edit.line_id, "excluded_domain",
            f"introduces {finance}; finance-related technology is not part of the candidate's work",
        )

    # 1. No invented figures. The single highest-risk fabrication, and the one the previous
    #    guard had no check for at all.
    new_numbers = {
        n for n in _numbers(after) - _numbers(before) if not _attributable(n, after, evidence_text)
    }
    if new_numbers:
        return Rejection(
            edit.line_id, "fabricated_metric",
            f"introduces {sorted(new_numbers)} which this bullet does not contain",
        )

    # 2. No technology, tool or proper noun that the CV does not contain somewhere. Checked
    #    against the whole CV, not just this bullet, so surfacing something the candidate
    #    genuinely has elsewhere stays legal.
    cv_tokens = _tokens(cv_text + " " + evidence_text)
    invented = {
        token
        for token in _named_things(after) - _named_things(before)
        if token not in cv_tokens and token not in _GENERIC_VOCABULARY
    }
    if invented:
        return Rejection(
            edit.line_id, "unsupported_technology",
            f"introduces {sorted(invented)} which appears nowhere in the CV",
        )

    # 3. No machine-written filler.
    hits = [p for p in BANNED_PHRASES if p in low_after and p not in low_before]
    if hits:
        return Rejection(edit.line_id, "ai_language", f"introduces {hits}")

    # 4. No new claim. Every meaningful word the edit introduces must be one the CV has
    #    earned — present in the CV, sharing a stem with something in it, or belonging to a
    #    requirement the evidence matcher confirmed the CV satisfies under other wording.
    #    Without this an edit can append a whole clause of capabilities the candidate never
    #    described, which is the most damaging kind of fabrication because it reads well.
    cv_tokens_all = _tokens(cv_text + " " + evidence_text)
    before_words = set(_content_words(before))
    unearned = sorted(
        {
            word
            for word in _content_words(after)
            if word not in before_words
            and not _word_supported(word, cv_tokens_all, set(allowed_terms))
        }
    )
    if unearned:
        return Rejection(
            edit.line_id, "unsupported_claim",
            f"introduces {unearned}, which the CV does not evidence anywhere",
        )

    # 4b. A skills row only grows: its label and every item stay, in order, and items are appended.
    if kind is LineKind.SKILL:
        problem = _skill_row_problem(before, after)
        if problem:
            return Rejection(edit.line_id, "skills_row", problem)
        return _evidence_problem(edit, after, before)

    # 5. No newly asserted ownership. Saying the candidate owned, led or defined something
    #    they only described participating in is a seniority claim, not a wording choice.
    new_ownership = [
        verb for verb in _OWNERSHIP_VERBS
        if re.search(rf"\b{verb}\b", low_after) and not re.search(rf"\b{verb}\b", low_before)
    ]
    if new_ownership:
        return Rejection(
            edit.line_id, "asserted_ownership",
            f"introduces {new_ownership}, claiming ownership the original line did not",
        )

    # 6. No keyword loss. Tailoring adds relevance; it never costs the candidate a term they
    #    already had. The planner deleted "AI" from "AI Product Manager" to bring the words
    #    "Product Manager" together — a tidier phrase and a strictly worse résumé.
    dropped = sorted(_named_things(before) - _tokens(after))
    if dropped:
        return Rejection(
            edit.line_id, "keyword_loss",
            f"removes {dropped}, which the original line had earned",
        )

    # 7. No new clause. Word-level permission is not enough on its own: "supporting analytics
    #    and machine learning workflows" is built entirely from words the CV contains, and
    #    appending it to a bullet that never mentioned ML workflows still invents a capability.
    #    Weaving a term into existing structure is an edit; bolting a clause onto the end is a
    #    claim. The difference is measurable as the size of the inserted run.
    runs, inserted_total = _insertions(before, after)
    longest = max(runs, default=0)
    trusted = bool(evidence_text.strip())
    max_run = _TRUSTED_INSERT_RUN if trusted else _MAX_INSERT_RUN
    max_total = _TRUSTED_INSERT_TOTAL if trusted else _MAX_INSERT_TOTAL
    if longest > max_run:
        return Rejection(
            edit.line_id, "appended_clause",
            f"inserts {longest} consecutive new words; an edit weaves terms in, it does not "
            "append a new clause",
        )
    if inserted_total > max_total:
        return Rejection(
            edit.line_id, "excessive_insertion",
            f"inserts {inserted_total} new words across the line",
        )

    # 8. No claim escalation.
    for weak, strongs in _ESCALATIONS:
        if weak in low_before and weak not in low_after:
            arrived = [s for s in strongs if re.search(rf"\b{re.escape(s)}\b", low_after)]
            if arrived:
                return Rejection(
                    edit.line_id, "claim_escalation",
                    f"replaces '{weak}' with {arrived}, overstating involvement",
                )

    # 9. Proportionate length. A ratio alone is wrong for short lines: turning "Built vector
    #    search" into "Built semantic search and data discovery" is a reasonable terminology
    #    edit that trips a 1.45x rule purely because the original was four words. Allow the
    #    larger of the ratio and a flat character allowance.
    ratio = len(after) / max(1, len(before))
    grew_by = len(after) - len(before)
    ratio_cap = _TRUSTED_LENGTH_RATIO if trusted else _MAX_LENGTH_RATIO
    growth_cap = _TRUSTED_LENGTH_GROWTH if trusted else _MAX_LENGTH_GROWTH
    if ratio > ratio_cap and grew_by > growth_cap:
        return Rejection(
            edit.line_id, "excessive_expansion", f"grows {ratio:.2f}x (+{grew_by} chars)"
        )
    if ratio < _MIN_LENGTH_RATIO:
        return Rejection(edit.line_id, "excessive_removal", f"shrinks to {ratio:.2f}x")

    # 10. Evidence that actually points at something.
    problem = _evidence_problem(edit, after, before)
    if problem:
        return problem

    # 11. An edit that changes nothing is noise in the change log.
    if after == before.strip():
        return Rejection(edit.line_id, "no_op", "after_text is identical to the original")

    return None


def _evidence_problem(edit: ProposedEdit, after: str, before: str) -> Rejection | None:
    """The edit's cited evidence must say something, and the edit must change the line.

    Substance is what matters, not whether the sentence happens to contain the words "the CV".
    Rejecting on a contained phrase threw out "The CV describes integrating Google Cloud services
    for geospatial and model-serving capabilities", a direct, specific citation, purely for
    naming the document it was citing.
    """
    evidence = (edit.evidence or "").strip().lower()
    stripped = evidence
    for filler in _VAGUE_EVIDENCE:
        stripped = stripped.replace(filler, " ")
    if len(evidence) < 12 or len(_content_words(stripped)) < 4:
        return Rejection(edit.line_id, "vague_evidence", f"evidence was {edit.evidence!r}")
    if after.strip() == before.strip():
        return Rejection(edit.line_id, "no_op", "after_text is identical to the original")
    return None


def _skill_row_problem(before: str, after: str) -> str | None:
    """Why ``after`` is not the same skills row with items appended, or ``None`` if it is."""
    kept = before.rstrip().rstrip(",;")
    if not after.startswith(kept):
        return "the row's label and existing items must stay exactly as they are, in order"
    tail = after[len(kept):].strip()
    if not tail:
        return "no item was added"
    if not tail.startswith((",", ";")):
        return "new items must be appended after a comma"
    items = [t for t in re.split(r"[,;]", tail) if t.strip()]
    if len(items) > _MAX_SKILL_ITEMS:
        return f"{len(items)} items appended; at most {_MAX_SKILL_ITEMS} per row"
    return None


def validate_edits(
    doc: ResumeDocument,
    edits: list[ProposedEdit],
    allowed_terms: frozenset[str] = frozenset(),
    evidence_text: str = "",
) -> ValidationReport:
    """Filter a plan down to the edits that obey the rules.

    ``allowed_terms`` are the posting's words that the evidence matcher confirmed the CV
    satisfies under different wording. They are the only vocabulary an edit may introduce
    that the CV does not already contain.
    """
    report = ValidationReport()
    cv_text = doc.to_text()
    seen: set[str] = set()

    for edit in edits:
        line = doc.bullet_by_id(edit.line_id)
        if line is None:
            report.rejected.append(
                Rejection(edit.line_id, "unknown_line", "no such editable line")
            )
            continue
        if edit.line_id in seen:
            report.rejected.append(
                Rejection(edit.line_id, "duplicate", "line already edited in this plan")
            )
            continue
        failure = check_edit(edit, line.text, cv_text, allowed_terms, evidence_text, line.kind)
        if failure:
            report.rejected.append(failure)
            continue
        seen.add(edit.line_id)
        report.accepted.append(edit)

    return report


def validate_document(
    original: ResumeDocument, tailored: ResumeDocument, report: ValidationReport
) -> ValidationReport:
    """Check that the pass changed only what it was allowed to change.

    These are the guarantees the operator is actually relying on when they submit the file,
    so a failure here stops the pass rather than annotating it.
    """
    if original.fingerprint() != tailored.fingerprint():
        report.document_failures.append(
            "immutable content changed: an employer, title, date, heading or skills row moved"
        )

    if [s.heading for s in original.sections] != [s.heading for s in tailored.sections]:
        report.document_failures.append("section names or order changed")

    if len(original.bullets()) != len(tailored.bullets()):
        report.document_failures.append(
            f"bullet count changed: {len(original.bullets())} -> {len(tailored.bullets())}"
        )

    for section_before, section_after in zip(original.sections, tailored.sections, strict=False):
        if len(section_before.lines) != len(section_after.lines):
            report.document_failures.append(
                f"line count changed in {section_before.heading or '(summary)'!r}"
            )

    preserved = preserved_ratio(original, tailored)
    if preserved < MIN_PRESERVED_RATIO:
        report.document_failures.append(
            f"EXCESSIVE TRANSFORMATION: only {preserved:.0%} of the original wording survived "
            f"(floor is {MIN_PRESERVED_RATIO:.0%})"
        )

    banned = [
        phrase
        for phrase in BANNED_PHRASES
        if phrase in tailored.to_text().lower() and phrase not in original.to_text().lower()
    ]
    if banned:
        report.document_failures.append(f"AI-language introduced: {banned}")

    return report


def preserved_ratio(original: ResumeDocument, tailored: ResumeDocument) -> float:
    """Share of the original document's words that are still present, in place.

    Measured per line rather than as a bag of words: moving a word from one bullet to another
    is a change the operator should see, not a preservation to be credited.
    """
    before = {ln.id: ln.text for ln in original.all_lines()}
    after = {ln.id: ln.text for ln in tailored.all_lines()}
    total = kept = 0
    for line_id, text in before.items():
        words = text.split()
        total += len(words)
        if after.get(line_id, "") == text:
            kept += len(words)
        else:
            new_words = set(after.get(line_id, "").split())
            kept += sum(1 for w in words if w in new_words)
    return 1.0 if total == 0 else kept / total
