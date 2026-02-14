from datetime import timedelta
from typing import cast

from django.utils import timezone

from apps.agents.models import Agent, ApprovalMode
from apps.approvals.models import ApprovalChannel, ApprovalRequest, TimeoutPolicy
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
        required_approvals = max(1, int(intent.agent.required_approvals))
        timeout_policy = self._timeout_policy(intent.agent)

        approval_request = ApprovalRequest.objects.create(
            agent=intent.agent,
            requested_by=intent.agent.owner,
            channel=channel,
            required_approvals=required_approvals,
            timeout_policy=timeout_policy,
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
        channels = self._configured_channels(intent.agent, fallback=channel)
        if ApprovalChannel.TELEGRAM in channels:
            from apps.approvals.tasks import notify_approval_request_task

            notify_approval_request_task.delay(approval_request.id)

        return cast(ApprovalRequest, approval_request)

    @staticmethod
    def _configured_channels(agent: Agent, fallback: str) -> set[str]:
        configured = agent.config.get("approval_channels", [])
        if isinstance(configured, list):
            normalized = {str(item).lower() for item in configured}
            if normalized:
                return normalized
        return {fallback}

    @staticmethod
    def _timeout_policy(agent: Agent) -> str:
        policy = str(agent.config.get("timeout_policy", TimeoutPolicy.AUTO_REJECT)).lower()
        allowed = {"auto_reject", "auto_pause", "escalate"}
        if policy in allowed:
            return policy
        return "auto_reject"
