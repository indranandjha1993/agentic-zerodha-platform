from django.utils import timezone

from apps.agents.models import Agent
from apps.execution.models import IntentStatus, Side, TradeIntent
from apps.execution.services.order_executor import TradeIntentExecutor


class AgentRuntime:
    def __init__(self, executor: TradeIntentExecutor | None = None) -> None:
        self.executor = executor or TradeIntentExecutor()

    def run(self, agent: Agent) -> dict[str, str]:
        symbol = agent.config.get("symbol", "INFY")
        quantity = int(agent.config.get("quantity", 1))

        intent = TradeIntent.objects.create(
            agent=agent,
            symbol=symbol,
            side=Side.BUY,
            quantity=quantity,
            status=IntentStatus.DRAFT,
            request_payload={"source": "agent_runtime", "agent_id": str(agent.id)},
        )

        result = self.executor.process(intent)
        agent.last_run_at = timezone.now()
        agent.save(update_fields=["last_run_at", "updated_at"])
        return result
