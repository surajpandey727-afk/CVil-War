"""Multi-agent orchestration: single-responsibility agents, a shared run log, and a real
LangGraph state graph wiring the ones with a natural per-item pipeline together.

Five named agents (``models.enums.AgentName``), each an existing service boundary — this
package does not invent new responsibilities, it makes the activity of ones that already
exist visible and, where they form a genuine sequence, orchestrates them:

* **Discovery** — ``services.discovery_scheduler``, the periodic cron sweep.
* **Eligibility** — ``core.sponsorship.classify``, visa-sponsorship classification.
* **Scoring** — ``services.resume_recommendation``, which résumé fits a job.
* **Application** — the apply pipeline in ``workers.tasks``.
* **Tracking** — reserved for the Apollo/Gmail communications workstream.

:mod:`recorder` is the shared instrumentation every agent uses to write an ``AgentRun`` row
and publish a live WebSocket event. :mod:`graph` is a real, compiled LangGraph
:class:`~langgraph.graph.StateGraph` chaining Eligibility → Scoring for one job after it is
enriched — the one point in the system where two agents already run against the same item in
a fixed order, so orchestrating it is honest rather than a hollow demonstration. Discovery and
Application are recorded but not LangGraph-orchestrated: each already has its own real trigger
(a cron tick; an apply-worker job) that a graph would not replace, only wrap.
"""
