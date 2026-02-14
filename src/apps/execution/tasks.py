from typing import Any

from celery import shared_task

from apps.execution.models import TradeIntent
from apps.execution.services.order_executor import TradeIntentExecutor


@shared_task(bind=True, max_retries=3)
def execute_intent_task(self: Any, intent_id: int) -> dict[str, str]:
    intent = TradeIntent.objects.select_related("agent", "agent__risk_policy").get(id=intent_id)
    executor = TradeIntentExecutor()
    return executor.process(intent)
