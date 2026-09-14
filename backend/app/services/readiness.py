"""Can the agent actually apply to this job, and if not, what is missing?

Asked *before* the operator commits, not discovered by the worker afterwards. The prerequisite
checks in ``runtime/apply.py`` are correct but they run too late to be useful: by then the
application is queued, the run fails terminally, and the operator learns that a LinkedIn
session was needed from a failure message on a dead application.

This asks the same questions up front and returns each unmet one as a blocker carrying the
action that clears it, so the screen can offer "Connect LinkedIn" instead of reporting a
failure after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.automation.connect import connectable
from app.core.llm.requirements import llm_key_required
from app.core.secrets.credential_store import CredentialStore
from app.models.job import Job
from app.models.resume import Resume
from app.models.user_llm_config import UserLLMConfig

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Blocker:
    """One unmet prerequisite, and the action that clears it.

    ``action`` is what the UI should offer. A blocker with no action would be a dead end,
    which is the failure mode this whole object exists to prevent.
    """

    code: str
    message: str
    action: str          # connect_platform | attach_resume | configure_llm | manual_only
    #: The platform the action applies to, when the action needs one.
    platform: str = ""
    #: True when the operator can still apply by hand — never leave them with nothing.
    manual_possible: bool = True


async def apply_readiness(
    db: AsyncSession, user_id: str, job: Job, *, resume_id: str | None = None
) -> list[Blocker]:
    """Every reason the agent could not apply to ``job`` right now, in the order to fix them.

    An empty list means the agent can run. The checks mirror ``run_apply`` deliberately: if
    they drift, the operator is told they are ready and the worker then fails, which is worse
    than no check at all. The test suite pins them against each other.
    """
    blockers: list[Blocker] = []
    platform = (job.platform or "").strip().lower()

    # 1. A session for the platform, when the platform is one you sign in to.
    if connectable(platform):
        state = await CredentialStore().load_session_cookies(db, user_id, platform)
        if state is None:
            blockers.append(Blocker(
                code="no_session",
                message=(
                    f"The agent has no {job.platform} session. Connect {job.platform} and sign "
                    "in yourself — your password is never seen or stored."
                ),
                action="connect_platform",
                platform=platform,
            ))
    elif not job.application_url and not job.url:
        # Not a login platform and no link to hand over: there is nothing to drive.
        blockers.append(Blocker(
            code="no_route",
            message="This listing has no application link, so there is nothing to open.",
            action="manual_only",
            manual_possible=False,
        ))

    # 2. A résumé to send.
    resume = await db.get(Resume, resume_id) if resume_id else None
    if resume is None:
        blockers.append(Blocker(
            code="no_resume",
            message="No CV is attached to this application yet.",
            action="attach_resume",
        ))
    elif not (resume.file_path_pdf or resume.file_path_docx):
        blockers.append(Blocker(
            code="resume_file_missing",
            message=f"'{resume.name}' has no rendered file to upload.",
            action="attach_resume",
        ))

    # 3. A model the agent can think with.
    cfg = (
        await db.execute(select(UserLLMConfig).where(UserLLMConfig.user_id == user_id))
    ).scalar_one_or_none()
    llm = get_settings().llm
    provider = cfg.preferred_provider if cfg else llm.preferred_provider
    model = cfg.default_model if cfg else llm.default_model
    # Bedrock authenticates through the AWS credential chain and a configured gateway uses
    # its own credential; in both cases demanding a per-user key blocks work that would
    # otherwise succeed. That is exactly what happened — every job reported "No API key is
    # configured for openai" while the client was routing happily through the local gateway.
    if llm_key_required(provider, model) and not await CredentialStore().get_llm_key(
        db, user_id, provider
    ):
        blockers.append(Blocker(
            code="no_llm_key",
            message=(
                f"No API key is configured for {provider}, and no gateway is set to supply "
                "one."
            ),
            action="configure_llm",
        ))

    return blockers
