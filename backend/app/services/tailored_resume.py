"""Generate a tailored résumé from the candidate's own PDF and store it as a version.

The base CV's PDF is the source of truth for how the document looks, so the tailored version is
that same PDF with a few paragraphs edited in place (see ``core.resume_tailoring.pdf_pipeline``).
Nothing here is allowed to report success the user cannot verify: a record is created only after
the generated file has been opened, parsed, validated and stored, and every way that can fail
surfaces as an error the person can act on.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GenerationError
from app.core.llm.factory import build_llm_client_for_user
from app.core.resume_tailoring.pdf_pipeline import tailor_pdf
from app.core.resume_tailoring.trusted import TrustedSource, profile_source, resume_source
from app.core.storage import StorageService, get_storage, keys
from app.core.storage.documents import PDF_CONTENT_TYPE
from app.models.job import Job
from app.models.resume import Resume
from app.models.user_settings import UserSettings
from app.schemas.resume import ResumeGenerateRequest, ResumeResponse
from app.services import ats_evaluation as ats

logger = structlog.get_logger(__name__)

#: One generation at a time per (user, base résumé, job). A double click, or a refresh while a
#: generation is running, waits for the first and then finds its result instead of paying for
#: and storing a second identical version.
_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}


def _display_name(base: Resume, job: Job) -> str:
    stem = Path(base.name).stem if base.name.lower().endswith((".pdf", ".docx")) else base.name
    label = f"{job.title} ({job.company})" if job.company else (job.title or "job")
    return f"{stem} - {label}"[:200]


async def _stored_pdf_exists(storage: StorageService, key: str | None) -> bool:
    if not key:
        return False
    try:
        await storage.get(key)
    except (FileNotFoundError, PermissionError, KeyError):
        return False
    return True


async def trusted_sources(db: AsyncSession, base: Resume, user_id: str) -> list[TrustedSource]:
    """The candidate's own records that may vouch for facts this PDF omitted.

    The structured profile and every OTHER base résumé. Generated (tailored/optimised) résumés
    are excluded: they derive from a base, so they cannot corroborate it.
    """
    sources: list[TrustedSource] = []
    settings = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    if settings is not None and (found := profile_source(settings.candidate_profile)):
        sources.append(found)
    others = (
        await db.execute(
            select(Resume).where(
                Resume.type == "base", Resume.id != base.id, Resume.archived_at.is_(None)
            ).order_by(Resume.created_at.desc()).limit(4)
        )
    ).scalars().all()
    for other in others:
        if found := resume_source(other.name, other.content_text):
            sources.append(found)
    return sources


async def existing_version(
    db: AsyncSession, storage: StorageService, base_id: str, job_id: str
) -> Resume | None:
    """The tailored version already made for this base and job, if its file still exists."""
    row = (
        await db.execute(
            select(Resume)
            .where(
                Resume.base_resume_id == base_id,
                Resume.job_id == job_id,
                Resume.type == "tailored",
                Resume.archived_at.is_(None),
            )
            .order_by(Resume.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is not None and await _stored_pdf_exists(storage, row.file_path_pdf):
        return row
    return None


async def generate_from_pdf(
    db: AsyncSession, base: Resume, job: Job, request: ResumeGenerateRequest, user_id: str
) -> ResumeResponse:
    storage = StorageService(get_storage(), user_id)
    lock = _LOCKS.setdefault((user_id, base.id, job.id), asyncio.Lock())
    async with lock:
        if not request.regenerate:
            found = await existing_version(db, storage, base.id, job.id)
            if found is not None:
                logger.info("tailored_resume_reused", resume_id=found.id, job_id=job.id)
                return ResumeResponse.model_validate(found)
        return await _generate(db, storage, base, job, user_id)


async def _generate(
    db: AsyncSession, storage: StorageService, base: Resume, job: Job, user_id: str
) -> ResumeResponse:
    if not ats.usable_posting(job):
        raise GenerationError(
            "This job has no description to tailor against. Open the posting and add its text first."
        )
    try:
        source = await storage.materialize_to_temp(base.file_path_pdf or "", suffix=".pdf")
    except (FileNotFoundError, PermissionError, KeyError, ValueError) as exc:
        raise GenerationError(
            "The stored PDF for this résumé is missing, so there is nothing to tailor. "
            "Upload it again and retry."
        ) from exc

    document_id = uuid.uuid4().hex
    out_dir = Path(tempfile.gettempdir()) / "cvilwar-tailored"
    out_path = out_dir / f"{document_id}.pdf"
    pdf_key = keys.resume_key(user_id, document_id, "pdf")
    started = datetime.now(UTC)
    stored = False
    try:
        llm = await build_llm_client_for_user(db, user_id)
        outcome = await tailor_pdf(
            source, out_path, job_text=ats.job_text(job), job_title=job.title or "", llm=llm,
            trusted=await trusted_sources(db, base, user_id),
        )

        try:
            await storage.put(pdf_key, out_path.read_bytes(), content_type=PDF_CONTENT_TYPE)
            stored = True
            # The write is verified by reading it back: "stored" must mean retrievable.
            if len(await storage.get(pdf_key)) != out_path.stat().st_size:
                raise OSError("stored size does not match")
        except Exception as exc:
            raise GenerationError(
                "The tailored PDF was generated but could not be stored, so nothing was saved. "
                "Please try again."
            ) from exc

        audit = outcome.audit.to_dict()
        audit.update(outcome.details)
        audit.update(
            {
                "generation_status": outcome.status,
                "validation_status": "passed",
                "base_resume_id": base.id,
                "job_id": job.id,
                "original_file": base.file_path_pdf,
                "tailored_file": pdf_key,
                "generated_at": started.isoformat(),
                "ats_scale": "0-100",
                "original_ats_score": outcome.before.total,
                "final_ats_score": outcome.after.total,
            }
        )
        tailored = Resume(
            user_id=user_id,
            name=_display_name(base, job),
            type="tailored",
            template_id=base.template_id,
            base_resume_id=base.id,
            job_id=job.id,
            file_path_pdf=pdf_key,
            content_text=outcome.final.to_text(),
            # Scores are 0-1 everywhere stored and 0-100 only on screen; the audit keeps the
            # 0-100 figures the engine reports.
            ats_score=outcome.after.total / 100.0,
            tailoring_audit=audit,
        )
        try:
            db.add(tailored)
            await db.commit()
            await db.refresh(tailored)
        except Exception as exc:
            await db.rollback()
            raise GenerationError(
                "The tailored PDF was generated but the version could not be recorded, so "
                "nothing was saved. Please try again."
            ) from exc
    except GenerationError:
        await _discard(storage, pdf_key, stored)
        raise
    except Exception as exc:
        logger.exception("tailored_resume_failed", base_id=base.id, job_id=job.id)
        await _discard(storage, pdf_key, stored)
        raise GenerationError(
            "The tailored PDF could not be generated. Nothing was saved — please try again."
        ) from exc
    finally:
        for leftover in (Path(source), out_path):
            with contextlib.suppress(OSError):
                leftover.unlink()

    logger.info(
        "tailored_resume_generated",
        resume_id=tailored.id,
        base_id=base.id,
        job_id=job.id,
        status=outcome.status,
        ats_before=outcome.before.total,
        ats_after=outcome.after.total,
        edits_applied=len(outcome.edit.applied),
        edits_skipped=len(outcome.edit.skipped),
    )
    return ResumeResponse.model_validate(tailored)


async def _discard(storage: StorageService, key: str, stored: bool) -> None:
    """Remove a generated file whose version record was never created."""
    if stored:
        with contextlib.suppress(Exception):
            await storage.delete(key)
