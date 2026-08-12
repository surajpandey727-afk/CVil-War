"""Harness review orchestrator: judge → diagnose → distil, run after each apply run.

This is the self-evolving loop's controller. The LLM client is injected (mockable). It
persists a verdict for every run, a diagnosis for non-success runs, and — when the
distiller finds durable, PII-free knowledge — a new domain skill that future runs reuse.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.harness import record, skills
from app.core.harness.diagnose import diagnose
from app.core.harness.distil import distil_skill
from app.core.harness.judge import judge_run
from app.models.enums import RunVerdictResult
from app.models.harness import RunTrajectory

logger = structlog.get_logger(__name__)


async def review_run(
    db: AsyncSession, llm: Any, traj: RunTrajectory, signals: dict | None = None
) -> dict:
    """Judge the run, diagnose any failure, and distil a reusable skill."""
    signals = signals or {}
    summary = {
        "application_id": traj.application_id,
        "platform": traj.platform,
        "agent_self_report": traj.agent_self_report,
        "status": traj.status,
        **signals,
    }

    judge = await judge_run(llm, summary)
    await record.record_verdict(db, user_id=traj.user_id, run_id=traj.id, judge=judge)

    failure_class = None
    if judge.verdict != RunVerdictResult.SUCCESS:
        diagnosis = diagnose(signals)
        await record.record_diagnosis(
            db, user_id=traj.user_id, run_id=traj.id, diagnosis=diagnosis, signals=signals
        )
        failure_class = diagnosis.failure_class

    distilled = await distil_skill(llm, traj.platform, summary)
    skill_id = None
    if distilled.worth_saving and distilled.content.strip():
        skill = await skills.record_skill(
            db, traj.platform, distilled.content, created_by="distiller"
        )
        skill_id = skill.id if skill else None  # None ⇒ rejected by the PII gate

    logger.info(
        "harness.review_complete",
        run_id=traj.id,
        verdict=judge.verdict,
        failure_class=failure_class,
        skill_saved=skill_id is not None,
    )
    return {"verdict": judge.verdict, "failure_class": failure_class, "skill_id": skill_id}
