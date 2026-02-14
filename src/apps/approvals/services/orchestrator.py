from datetime import timedelta
from typing import cast

from django.utils import timezone

from apps.agents.models import Agent, ApprovalMode
from apps.approvals.models import ApprovalRequest
from apps.execution.models import TradeIntent


class ApprovalOrchestrator:
    def requires_approval(self, agent: Agent, risk_score: int) -> bool:
        if agent.approval_mode == ApprovalMode.NONE:
            return False

        if agent.approval_mode == ApprovalMode.ALWAYS:
            return True

        threshold = int(agent.config.get("approval_risk_threshold", 50))
        return risk_score >= threshold

    def create_request(
        self,
        intent: TradeIntent,
        risk_score: int,
        channel: str = "dashboard",
    ) -> ApprovalRequest:
        ttl_minutes = int(intent.agent.config.get("approval_ttl_minutes", 10))

        approval_request = ApprovalRequest.objects.create(
            agent=intent.agent,
            requested_by=intent.agent.owner,
            channel=channel,
            intent_payload={
                "symbol": intent.symbol,
                "side": intent.side,
                "quantity": intent.quantity,
                "order_type": intent.order_type,
                "product": intent.product,
                "price": str(intent.price) if intent.price else None,
            },
            risk_snapshot={"risk_score": risk_score},
            expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
        )
        return cast(ApprovalRequest, approval_request)
