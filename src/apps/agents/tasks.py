from typing import Any

from celery import shared_task

from apps.agents.models import Agent, AgentAnalysisRun, AgentStatus, AnalysisRunStatus
from apps.agents.services.analysis_run_service import AgentAnalysisRunService
from apps.agents.services.openrouter_market_analyst import (
    MissingLlmCredentialError,
    OpenRouterAgentCanceledError,
    OpenRouterAgentError,
)
from apps.agents.services.runtime import AgentRuntime
from apps.audit.models import AuditEvent, AuditLevel


@shared_task(bind=True, max_retries=3)
def run_agent_task(self: Any, agent_id: int) -> dict[str, str]:
    agent = Agent.objects.get(id=agent_id)
    if agent.status != AgentStatus.ACTIVE or not agent.is_auto_enabled:
        return {"status": "skipped", "message": "Agent is not active/auto-enabled."}

    runtime = AgentRuntime()
    return runtime.run(agent)


@shared_task(bind=True, max_retries=2)
def execute_agent_analysis_run_task(self: Any, run_id: int) -> dict[str, Any]:
    run = AgentAnalysisRun.objects.select_related("agent", "requested_by").get(id=run_id)
    if run.status == AnalysisRunStatus.CANCELED:
        return {"status": "canceled", "run_id": run.id}
    if run.status not in {AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING}:
        return {"status": "skipped", "run_id": run.id, "run_status": run.status}

    service = AgentAnalysisRunService()
    try:
        result = service.execute(run)
    except OpenRouterAgentCanceledError:
        return {"status": "canceled", "run_id": run.id}
    except MissingLlmCredentialError as exc:
        AuditEvent.objects.create(
            actor=run.requested_by,
            event_type="agent_market_analysis_failed",
            level=AuditLevel.WARNING,
            entity_type="agent_analysis_run",
            entity_id=str(run.id),
            payload={"error": str(exc)},
            message="OpenRouter credential missing for async analysis run.",
        )
        return {"status": "failed", "run_id": run.id, "error": str(exc)}
    except OpenRouterAgentError as exc:
        AuditEvent.objects.create(
            actor=run.requested_by,
            event_type="agent_market_analysis_failed",
            level=AuditLevel.ERROR,
            entity_type="agent_analysis_run",
            entity_id=str(run.id),
            payload={"error": str(exc)},
            message="OpenRouter market analysis failed for async run.",
        )
        return {"status": "failed", "run_id": run.id, "error": str(exc)}

    if result.get("status") == "canceled":
        return {"status": "canceled", "run_id": run.id}

    AuditEvent.objects.create(
        actor=run.requested_by,
        event_type="agent_market_analysis_completed",
        level=AuditLevel.INFO,
        entity_type="agent_analysis_run",
        entity_id=str(run.id),
        payload={
            "model": result.get("model"),
            "steps_executed": result.get("steps_executed"),
        },
        message="OpenRouter market analysis completed for async run.",
    )
    return {"status": "completed", "run_id": run.id}
