from typing import Any

from celery import shared_task

from apps.agents.models import Agent, AgentStatus
from apps.agents.services.runtime import AgentRuntime


@shared_task(bind=True, max_retries=3)
def run_agent_task(self: Any, agent_id: int) -> dict[str, str]:
    agent = Agent.objects.get(id=agent_id)
    if agent.status != AgentStatus.ACTIVE or not agent.is_auto_enabled:
        return {"status": "skipped", "message": "Agent is not active/auto-enabled."}

    runtime = AgentRuntime()
    return runtime.run(agent)
