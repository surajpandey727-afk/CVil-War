"""Post-enrichment agent pipeline — Eligibility then Scoring, as a real LangGraph state graph.

Triggered once a job's full posting text is known (``services.enrichment.enrich_job``): the
one point in this system where two single-responsibility agents genuinely need to run in a
fixed order against the same item. A fuller description improves both the sponsorship signal
(Eligibility) and the résumé match (Scoring), so re-running both automatically is worth doing
rather than waiting for the operator to notice and re-trigger each by hand.

Discovery and Application are NOT wired into this graph — each already has its own real
trigger (a cron tick; an apply-worker job) that a graph would only wrap, not replace. Adding
them here would be orchestration in name only.
"""

from __future__ import annotations

from typing import Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.orchestration.recorder import record_agent_run
from app.core.sponsorship.classify import classify as classify_sponsor
from app.models.enums import AgentName
from app.models.job import Job
from app.services.resume_recommendation import recommend_best_resume

logger = structlog.get_logger(__name__)


class PipelineState(TypedDict):
    """Everything one run of the graph needs. Not persisted/checkpointed — this graph runs
    once, start to finish, in a single ``ainvoke`` call, so a plain in-memory dict is enough."""

    db: AsyncSession
    user_id: str
    redis: Any | None
    job_id: str
    company: str
    description: str


async def _eligibility_node(state: PipelineState) -> dict[str, Any]:
    db, user_id, redis = state["db"], state["user_id"], state["redis"]
    async with record_agent_run(
        db, user_id, AgentName.ELIGIBILITY,
        input_summary=f"Re-classify sponsorship for job {state['job_id']}",
        linked_entity_type="job", linked_entity_id=state["job_id"], redis=redis,
    ) as run:
        confidence, evidence = classify_sponsor(state["company"], state["description"])
        job = await db.get(Job, state["job_id"])
        if job is not None:
            job.sponsor_confidence = confidence
            job.sponsor_evidence = evidence
            await db.commit()
        run.output_summary = confidence.value + (f": {evidence}" if evidence else "")
    return {}


async def _scoring_node(state: PipelineState) -> dict[str, Any]:
    db, user_id, redis = state["db"], state["user_id"], state["redis"]
    async with record_agent_run(
        db, user_id, AgentName.SCORING,
        input_summary=f"Recommend best résumé for job {state['job_id']}",
        linked_entity_type="job", linked_entity_id=state["job_id"], redis=redis,
    ) as run:
        recommendation = await recommend_best_resume(db, state["job_id"])
        run.output_summary = (recommendation.synopsis or "No résumés to score.")[:300]
    return {}


def _build_graph() -> Any:
    builder = StateGraph(PipelineState)
    builder.add_node("eligibility", _eligibility_node)
    builder.add_node("scoring", _scoring_node)
    builder.set_entry_point("eligibility")
    builder.add_edge("eligibility", "scoring")
    builder.add_edge("scoring", END)
    return builder.compile()


#: Built once per process. Compiling is pure graph-structure construction (no I/O), so
#: caching it is a straightforward win — every invocation supplies its own state via
#: ainvoke() and none of them share mutable graph-level state.
_graph: Any | None = None


def _get_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


async def run_post_enrichment_pipeline(
    db: AsyncSession, user_id: str, job: Job, *, redis: Any | None = None
) -> None:
    """Run Eligibility then Scoring for one job, through the compiled LangGraph graph.

    Best-effort: a failure here must not take down the enrichment request that triggered it.
    The operator already sees the enrichment succeed regardless; a failed re-classification
    shows up in the Agent Ops log (``record_agent_run`` always closes its row, even on error)
    rather than as a 500 on an otherwise-unrelated action.
    """
    graph = _get_graph()
    try:
        await graph.ainvoke({
            "db": db, "user_id": user_id, "redis": redis,
            "job_id": job.id, "company": job.company, "description": job.description or "",
        })
    except Exception as exc:
        logger.warning(
            "orchestration.post_enrichment_pipeline_failed", job_id=job.id, error=str(exc)
        )
