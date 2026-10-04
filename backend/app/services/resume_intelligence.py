"""Resume Intelligence: master résumé, role branches, git-style versioning, and the change log.

The master résumé is the lineage of ``ResumeVersion`` rows with ``branch_id IS NULL`` for a
user; a role branch is a ``ResumeBranch`` row whose own version lineage was seeded from the
master's content at creation time. Every write here creates a NEW version rather than
mutating an old one — nothing is ever deleted or silently rewritten (the product's core
"never silently alter the master" requirement).

Job-specific tailoring (the LLM-backed gap analysis and change generation) lives in
``services.resume_tailoring`` — a deliberately separate module, since it is the one part of
this system that costs an LLM call and must never run on a passive page view.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import RecordNotFoundError
from app.models.enums import ResumeChangeStatus, ResumeChangeType, ResumeVersionSource, RoleFamily
from app.models.resume_intelligence import ResumeBranch, ResumeChange, ResumeVersion
from app.models.user_settings import UserSettings
from app.schemas.resume_intelligence import (
    Achievement,
    CreateBranchRequest,
    EducationEntry,
    ExperienceEntry,
    ResumeBranchDetail,
    ResumeBranchSummary,
    ResumeChangeOut,
    ResumeContent,
    ResumeHeader,
    ResumeIntelligenceOverview,
    ResumeVersionDetail,
    ResumeVersionSummary,
    VersionDiff,
    VersionDiffEntry,
)

logger = structlog.get_logger(__name__)


def _new_id() -> str:
    return uuid.uuid4().hex


def _content_hash(content: dict) -> str:
    """Deterministic hash of a content blob — used for cheap identity checks (e.g. "does the
    version an application recorded still match what's live"), not for security."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _empty_content() -> ResumeContent:
    return ResumeContent()


async def _bootstrap_master_content(db: AsyncSession, user_id: str) -> ResumeContent:
    """Seed a first master résumé from whatever real data already exists, rather than an
    empty form — ``UserSettings.candidate_profile`` (already populated for this product's
    real user) and the most recently updated uploaded résumé's parsed text, best-effort.
    Never fabricates anything not already on file.
    """
    settings_row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    profile = (settings_row.candidate_profile or {}) if settings_row else {}

    header = ResumeHeader(
        full_name=str(profile.get("full_name") or ""),
        email=str(profile.get("email") or ""),
        phone=str(profile.get("phone") or ""),
        location=str(profile.get("location") or ""),
        linkedin_url=str(profile.get("linkedin_url") or ""),
        github_url=str(profile.get("github_url") or ""),
    )
    experience = []
    for entry in profile.get("experience") or []:
        if not isinstance(entry, dict):
            continue
        desc = str(entry.get("description") or "")
        achievements = [
            Achievement(id=_new_id(), text=str(r))
            for r in (entry.get("responsibilities") or [])
            if str(r).strip()
        ]
        if desc.strip():
            achievements.insert(0, Achievement(id=_new_id(), text=desc))
        experience.append(ExperienceEntry(
            id=_new_id(),
            title=str(entry.get("title") or ""),
            company=str(entry.get("company") or ""),
            start_date=str(entry.get("start_date") or ""),
            end_date=str(entry.get("end_date") or ""),
            achievements=achievements,
        ))
    education = [
        EducationEntry(
            degree=str(e.get("degree") or ""), institution=str(e.get("institution") or ""),
            graduation_year=str(e.get("graduation_year") or ""),
        )
        for e in (profile.get("education") or []) if isinstance(e, dict)
    ]

    return ResumeContent(
        header=header,
        summary=str(profile.get("summary") or ""),
        experience=experience,
        education=education,
        skills=[s for s in (profile.get("skills") or []) if isinstance(s, str)],
        certifications=[c for c in (profile.get("certifications") or []) if isinstance(c, str)],
    )


def _version_label(prefix: str, sequence: int) -> str:
    """"MAIN v1.0", "AI Product Manager v1.3" — a flat minor counter, not real semver. See
    the product brief: "do not create complicated semantic versioning unless necessary"."""
    return f"{prefix} v1.{sequence - 1}"


async def latest_version(
    db: AsyncSession, user_id: str, branch_id: str | None,
) -> ResumeVersion | None:
    result = await db.execute(
        select(ResumeVersion)
        .where(ResumeVersion.user_id == user_id, ResumeVersion.branch_id == branch_id)
        .order_by(ResumeVersion.sequence.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_version(
    db: AsyncSession, user_id: str, *, branch_id: str | None, content: ResumeContent,
    source: ResumeVersionSource, commit_message: str, label_prefix: str,
    parent: ResumeVersion | None,
) -> ResumeVersion:
    sequence = (parent.sequence + 1) if parent else 1
    version = ResumeVersion(
        user_id=user_id, branch_id=branch_id, parent_version_id=parent.id if parent else None,
        version_label=_version_label(label_prefix, sequence), sequence=sequence,
        content=content.model_dump(), content_hash=_content_hash(content.model_dump()),
        source=source, commit_message=commit_message,
    )
    db.add(version)
    await db.flush()
    return version


def version_summary(v: ResumeVersion) -> ResumeVersionSummary:
    return ResumeVersionSummary(
        id=v.id, branch_id=v.branch_id, version_label=v.version_label, sequence=v.sequence,
        source=str(v.source), commit_message=v.commit_message, content_hash=v.content_hash,
        created_at=v.created_at,
    )


def _out_change(c: ResumeChange) -> ResumeChangeOut:
    return ResumeChangeOut(
        id=c.id, change_type=str(c.change_type), section=c.section,
        before_text=c.before_text, after_text=c.after_text, reason=c.reason,
        source_job_id=c.source_job_id, evidence=c.evidence, status=str(c.status),
        created_at=c.created_at,
    )


async def get_or_create_master(db: AsyncSession, user_id: str) -> ResumeVersion:
    """The latest master version, bootstrapping a v1.0 from existing data if none exists yet —
    "seamless" per the product brief: no forced separate onboarding step."""
    latest = await latest_version(db, user_id, branch_id=None)
    if latest is not None:
        return latest
    content = await _bootstrap_master_content(db, user_id)
    version = await create_version(
        db, user_id, branch_id=None, content=content, source=ResumeVersionSource.INITIAL,
        commit_message="Initial master résumé", label_prefix="MAIN", parent=None,
    )
    await db.commit()
    await db.refresh(version)
    logger.info("resume_intelligence.master_bootstrapped", user_id=user_id)
    return version


async def update_master(
    db: AsyncSession, user_id: str, content: ResumeContent, commit_message: str,
) -> ResumeVersion:
    """A direct user edit to the master. Diffed against the prior version so the edit still
    lands in the change log — a user edit is a change like any other, just already accepted."""
    parent = await get_or_create_master(db, user_id)
    new_version = await create_version(
        db, user_id, branch_id=None, content=content, source=ResumeVersionSource.USER_EDIT,
        commit_message=commit_message, label_prefix="MAIN", parent=parent,
    )
    await _record_diff_as_changes(db, user_id, new_version.id, parent.content, content.model_dump())
    await db.commit()
    await db.refresh(new_version)
    return new_version


async def list_branches(db: AsyncSession, user_id: str) -> list[ResumeBranchSummary]:
    result = await db.execute(
        select(ResumeBranch).where(ResumeBranch.user_id == user_id).order_by(ResumeBranch.created_at)
    )
    branches = result.scalars().all()
    out = []
    for b in branches:
        latest = await latest_version(db, user_id, branch_id=b.id)
        out.append(ResumeBranchSummary(
            id=b.id, role_name=b.role_name, role_family=str(b.role_family),
            description=b.description,
            current_version=version_summary(latest) if latest else None,
            market_signals_computed_at=b.market_signals_computed_at,
        ))
    return out


async def create_branch(
    db: AsyncSession, user_id: str, data: CreateBranchRequest,
) -> ResumeBranchSummary:
    """Seeds the branch's first version from the master's CURRENT content — a role branch
    starts as a copy of the facts, never invented content (MASTER -> ROLE -> JOB per the
    architecture requirement)."""
    master = await get_or_create_master(db, user_id)
    try:
        family = RoleFamily(data.role_family)
    except ValueError:
        family = RoleFamily.PRODUCT
    branch = ResumeBranch(
        user_id=user_id, role_name=data.role_name, role_family=family,
        description=data.description,
    )
    db.add(branch)
    await db.flush()
    version = await create_version(
        db, user_id, branch_id=branch.id,
        content=ResumeContent.model_validate(master.content),
        source=ResumeVersionSource.INITIAL,
        commit_message=f"Branched from {master.version_label}", label_prefix=data.role_name,
        parent=None,
    )
    await db.commit()
    await db.refresh(branch)
    logger.info("resume_intelligence.branch_created", user_id=user_id, branch_id=branch.id)
    return ResumeBranchSummary(
        id=branch.id, role_name=branch.role_name, role_family=str(branch.role_family),
        description=branch.description, current_version=version_summary(version),
        market_signals_computed_at=None,
    )


async def get_branch(db: AsyncSession, user_id: str, branch_id: str) -> ResumeBranchDetail:
    branch = (
        await db.execute(
            select(ResumeBranch).where(ResumeBranch.id == branch_id, ResumeBranch.user_id == user_id)
        )
    ).scalar_one_or_none()
    if branch is None:
        raise RecordNotFoundError("ResumeBranch", branch_id)
    latest = await latest_version(db, user_id, branch_id=branch.id)
    return ResumeBranchDetail(
        id=branch.id, role_name=branch.role_name, role_family=str(branch.role_family),
        description=branch.description,
        current_version=version_summary(latest) if latest else None,
        market_signals_computed_at=branch.market_signals_computed_at,
        current_content=ResumeContent.model_validate(latest.content) if latest else None,
        market_signals=branch.market_signals,
    )


async def delete_branch(db: AsyncSession, user_id: str, branch_id: str) -> None:
    branch = (
        await db.execute(
            select(ResumeBranch).where(ResumeBranch.id == branch_id, ResumeBranch.user_id == user_id)
        )
    ).scalar_one_or_none()
    if branch is None:
        raise RecordNotFoundError("ResumeBranch", branch_id)
    await db.delete(branch)
    await db.commit()


async def list_versions(
    db: AsyncSession, user_id: str, branch_id: str | None,
) -> list[ResumeVersionDetail]:
    result = await db.execute(
        select(ResumeVersion)
        .where(ResumeVersion.user_id == user_id, ResumeVersion.branch_id == branch_id)
        .options(selectinload(ResumeVersion.changes))
        .order_by(ResumeVersion.sequence.desc())
    )
    versions = result.scalars().all()
    return [
        ResumeVersionDetail(
            **version_summary(v).model_dump(),
            content=ResumeContent.model_validate(v.content),
            changes=[_out_change(c) for c in v.changes],
        )
        for v in versions
    ]


async def get_version(db: AsyncSession, user_id: str, version_id: str) -> ResumeVersionDetail:
    version = (
        await db.execute(
            select(ResumeVersion)
            .where(ResumeVersion.id == version_id, ResumeVersion.user_id == user_id)
            .options(selectinload(ResumeVersion.changes))
        )
    ).scalar_one_or_none()
    if version is None:
        raise RecordNotFoundError("ResumeVersion", version_id)
    return ResumeVersionDetail(
        **version_summary(version).model_dump(),
        content=ResumeContent.model_validate(version.content),
        changes=[_out_change(c) for c in version.changes],
    )


async def get_version_row(db: AsyncSession, user_id: str, version_id: str) -> ResumeVersion:
    version = (
        await db.execute(
            select(ResumeVersion).where(
                ResumeVersion.id == version_id, ResumeVersion.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise RecordNotFoundError("ResumeVersion", version_id)
    return version


async def restore_version(
    db: AsyncSession, user_id: str, version_id: str, commit_message: str,
) -> ResumeVersionSummary:
    """Rollback creates a NEW version copying the restored content — history is never deleted
    or rewound in place (the product's explicit "never delete history" requirement)."""
    target = await get_version_row(db, user_id, version_id)
    current_head = await latest_version(db, user_id, branch_id=target.branch_id)
    label_prefix = "MAIN" if target.branch_id is None else (
        (await db.get(ResumeBranch, target.branch_id)).role_name
    )
    message = commit_message or f"Restored content from {target.version_label}"
    new_version = await create_version(
        db, user_id, branch_id=target.branch_id,
        content=ResumeContent.model_validate(target.content),
        source=ResumeVersionSource.RESTORED, commit_message=message,
        label_prefix=label_prefix, parent=current_head,
    )
    db.add(ResumeChange(
        user_id=user_id, version_id=new_version.id, change_type=ResumeChangeType.RESTORED,
        section="all", reason=message, status=ResumeChangeStatus.ACCEPTED,
        evidence=f"Restored from {target.version_label}",
    ))
    await db.commit()
    await db.refresh(new_version)
    return version_summary(new_version)


async def get_overview(db: AsyncSession, user_id: str) -> ResumeIntelligenceOverview:
    master = await get_or_create_master(db, user_id)
    branches = await list_branches(db, user_id)
    cutoff = datetime.now(UTC).timestamp() - 30 * 86400
    recent_count_result = await db.execute(
        select(ResumeChange.id).join(ResumeVersion).where(
            ResumeVersion.user_id == user_id,
            ResumeChange.created_at >= datetime.fromtimestamp(cutoff, tz=UTC),
        )
    )
    recent_count = len(recent_count_result.all())
    return ResumeIntelligenceOverview(
        master_version=version_summary(master), branches=branches,
        recent_changes_count=recent_count,
    )


# ---------------------------------------------------------------------------
# Diffing — used both for the change-log write path and the explicit diff view.
# ---------------------------------------------------------------------------


def _diff_scalar(section: str, path: str, before: str, after: str) -> VersionDiffEntry | None:
    if before == after:
        return None
    return VersionDiffEntry(section=section, path=path, before=before or None, after=after or None)


def _diff_list_of_strings(section: str, before: list[str], after: list[str]) -> tuple[list[VersionDiffEntry], list[VersionDiffEntry]]:
    before_set, after_set = set(before), set(after)
    added = [VersionDiffEntry(section=section, path=s, after=s) for s in sorted(after_set - before_set)]
    removed = [VersionDiffEntry(section=section, path=s, before=s) for s in sorted(before_set - after_set)]
    return added, removed


def diff_content(before: dict, after: dict) -> VersionDiff:
    """Structured, section-aware diff between two content blobs. Achievements/projects are
    compared by their own ``id`` where present (individually addressable, per the content
    model), falling back to text equality for legacy/bootstrapped entries with no id yet."""
    added: list[VersionDiffEntry] = []
    removed: list[VersionDiffEntry] = []
    modified: list[VersionDiffEntry] = []

    before_c = ResumeContent.model_validate(before)
    after_c = ResumeContent.model_validate(after)

    for field in ("full_name", "email", "phone", "location", "linkedin_url", "github_url"):
        entry = _diff_scalar("header", field, getattr(before_c.header, field), getattr(after_c.header, field))
        if entry:
            modified.append(entry)

    summary_diff = _diff_scalar("summary", "summary", before_c.summary, after_c.summary)
    if summary_diff:
        modified.append(summary_diff)

    a, r = _diff_list_of_strings("skills", before_c.skills, after_c.skills)
    added += a
    removed += r
    a, r = _diff_list_of_strings("certifications", before_c.certifications, after_c.certifications)
    added += a
    removed += r
    a, r = _diff_list_of_strings("additional", before_c.additional, after_c.additional)
    added += a
    removed += r

    before_ach = {
        (e.id or f"{ei}:{ai}"): a.text
        for ei, e in enumerate(before_c.experience) for ai, a in enumerate(e.achievements)
    }
    after_ach = {
        (e.id or f"{ei}:{ai}"): a.text
        for ei, e in enumerate(after_c.experience) for ai, a in enumerate(e.achievements)
    }
    for key in after_ach.keys() - before_ach.keys():
        added.append(VersionDiffEntry(section="experience", path=key, after=after_ach[key]))
    for key in before_ach.keys() - after_ach.keys():
        removed.append(VersionDiffEntry(section="experience", path=key, before=before_ach[key]))
    for key in before_ach.keys() & after_ach.keys():
        if before_ach[key] != after_ach[key]:
            modified.append(VersionDiffEntry(
                section="experience", path=key, before=before_ach[key], after=after_ach[key],
            ))

    return VersionDiff(from_version_id="", to_version_id="", added=added, removed=removed, modified=modified)


async def diff_versions(
    db: AsyncSession, user_id: str, from_id: str, to_id: str,
) -> VersionDiff:
    from_v = await get_version_row(db, user_id, from_id)
    to_v = await get_version_row(db, user_id, to_id)
    result = diff_content(from_v.content, to_v.content)
    result.from_version_id = from_id
    result.to_version_id = to_id
    return result


async def _record_diff_as_changes(
    db: AsyncSession, user_id: str, version_id: str, before: dict, after: dict,
) -> None:
    """Turns a content diff into individually-visible ResumeChange rows for a user-edit commit
    — a direct edit still gets full change-log traceability, not just a version bump."""
    diff = diff_content(before, after)
    for entry in diff.added:
        db.add(ResumeChange(
            user_id=user_id, version_id=version_id, change_type=ResumeChangeType.ADDED,
            section=entry.section, after_text=entry.after, reason="User edit",
            status=ResumeChangeStatus.ACCEPTED,
        ))
    for entry in diff.removed:
        db.add(ResumeChange(
            user_id=user_id, version_id=version_id, change_type=ResumeChangeType.REMOVED,
            section=entry.section, before_text=entry.before, reason="User edit",
            status=ResumeChangeStatus.ACCEPTED,
        ))
    for entry in diff.modified:
        db.add(ResumeChange(
            user_id=user_id, version_id=version_id, change_type=ResumeChangeType.MODIFIED,
            section=entry.section, before_text=entry.before, after_text=entry.after,
            reason="User edit", status=ResumeChangeStatus.ACCEPTED,
        ))
