from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone

from apps.approvals.models import (
    ApprovalChannel,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    DecisionType,
)
from apps.execution.models import IntentStatus
from apps.execution.tasks import execute_intent_task


class ApprovalDecisionConflictError(RuntimeError):
    """Raised when attempting to decide a non-pending approval request."""


class ApprovalDecisionService:
    def decide(
        self,
        *,
        approval_request: ApprovalRequest,
        actor: AbstractBaseUser | None,
        decision: str,
        channel: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        if approval_request.status != ApprovalStatus.PENDING:
            raise ApprovalDecisionConflictError("Approval request is no longer pending.")

        decision_payload = metadata or {}
        ApprovalDecision.objects.create(
            approval_request=approval_request,
            actor=actor,
            channel=channel,
            decision=decision,
            reason=reason,
            metadata=decision_payload,
        )

        approval_request.decided_by = actor
        approval_request.decided_at = timezone.now()
        approval_request.decision_reason = reason
        approval_request.status = (
            ApprovalStatus.APPROVED if decision == DecisionType.APPROVE else ApprovalStatus.REJECTED
        )
        approval_request.save(
            update_fields=[
                "decided_by",
                "decided_at",
                "decision_reason",
                "status",
                "updated_at",
            ]
        )

        trade_intent = getattr(approval_request, "trade_intent", None)
        if trade_intent is None:
            return approval_request

        if decision == DecisionType.APPROVE:
            trade_intent.status = IntentStatus.APPROVED
            trade_intent.failure_reason = ""
            trade_intent.save(update_fields=["status", "failure_reason", "updated_at"])
            execute_intent_task.delay(trade_intent.id, True)
            return approval_request

        trade_intent.status = IntentStatus.REJECTED
        trade_intent.failure_reason = reason or "Rejected by approver."
        trade_intent.save(update_fields=["status", "failure_reason", "updated_at"])
        return approval_request

    @staticmethod
    def default_reason_for_channel(decision: str, channel: str) -> str:
        if channel == ApprovalChannel.TELEGRAM and decision == DecisionType.APPROVE:
            return "Approved from Telegram."
        if channel == ApprovalChannel.TELEGRAM and decision == DecisionType.REJECT:
            return "Rejected from Telegram."
        return ""
