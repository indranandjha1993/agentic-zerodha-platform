from django.utils import timezone

from apps.agents.models import ExecutionMode
from apps.approvals.services.orchestrator import ApprovalOrchestrator
from apps.broker_kite.services.kite_adapter import KiteAdapter
from apps.execution.models import IntentStatus, TradeIntent
from apps.risk.services.policy_engine import RiskPolicyEngine


class TradeIntentExecutor:
    def __init__(
        self,
        risk_engine: RiskPolicyEngine | None = None,
        approval_orchestrator: ApprovalOrchestrator | None = None,
        kite_adapter: KiteAdapter | None = None,
    ) -> None:
        self.risk_engine = risk_engine or RiskPolicyEngine()
        self.approval_orchestrator = approval_orchestrator or ApprovalOrchestrator()
        self.kite_adapter = kite_adapter or KiteAdapter()

    def process(self, intent: TradeIntent) -> dict[str, str]:
        risk_decision = self.risk_engine.evaluate(intent=intent, policy=intent.agent.risk_policy)

        if not risk_decision.approved:
            intent.status = IntentStatus.REJECTED
            intent.failure_reason = risk_decision.reason
            intent.save(update_fields=["status", "failure_reason", "updated_at"])
            return {"status": intent.status, "reason": intent.failure_reason}

        if self.approval_orchestrator.requires_approval(
            agent=intent.agent,
            risk_score=risk_decision.risk_score,
        ):
            approval_request = self.approval_orchestrator.create_request(
                intent=intent,
                risk_score=risk_decision.risk_score,
            )
            intent.approval_request = approval_request
            intent.status = IntentStatus.PENDING_APPROVAL
            intent.save(update_fields=["approval_request", "status", "updated_at"])
            return {
                "status": intent.status,
                "approval_request_id": str(approval_request.id),
            }

        if intent.agent.execution_mode == ExecutionMode.PAPER:
            intent.status = IntentStatus.PLACED
            intent.broker_order_id = f"paper-{intent.id}"
            intent.broker_response = {"mode": "paper", "message": "Simulated order placement."}
            intent.placed_at = timezone.now()
            intent.save(
                update_fields=[
                    "status",
                    "broker_order_id",
                    "broker_response",
                    "placed_at",
                    "updated_at",
                ]
            )
            return {"status": intent.status, "order_id": intent.broker_order_id}

        order_response = self.kite_adapter.place_order(intent)
        intent.status = IntentStatus.PLACED
        intent.broker_order_id = str(order_response.get("order_id", ""))
        intent.broker_response = order_response
        intent.placed_at = timezone.now()
        intent.save(
            update_fields=[
                "status",
                "broker_order_id",
                "broker_response",
                "placed_at",
                "updated_at",
            ]
        )

        return {"status": intent.status, "order_id": intent.broker_order_id}
