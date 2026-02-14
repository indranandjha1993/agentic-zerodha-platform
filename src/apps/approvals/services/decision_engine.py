from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.approvals.models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    DecisionType,
)
from apps.execution.models import IntentStatus
from apps.execution.tasks import execute_intent_task


class ApprovalDecisionConflictError(RuntimeError):
    """Raised when attempting to decide a non-pending approval request."""


class ApprovalDecisionPermissionError(RuntimeError):
    """Raised when actor is not allowed to decide the approval request."""


class ApprovalDecisionDuplicateError(RuntimeError):
    """Raised when actor already submitted a decision for this request."""


@dataclass(slots=True)
class ApprovalDecisionOutcome:
    approval_request: ApprovalRequest
    status: str
    is_final: bool
    approved_count: int
    required_approvals: int


class ApprovalDecisionService:
    def decide(
        self,
        *,
        approval_request: ApprovalRequest,
        actor: Any,
        decision: str,
        channel: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalDecisionOutcome:
        if approval_request.status != ApprovalStatus.PENDING:
            raise ApprovalDecisionConflictError("Approval request is no longer pending.")

        if not self._can_user_decide(approval_request=approval_request, actor=actor):
            raise ApprovalDecisionPermissionError("You are not allowed to decide this request.")

        if self._actor_has_decided(approval_request=approval_request, actor=actor):
            raise ApprovalDecisionDuplicateError("You have already decided this request.")

        decision_payload = metadata or {}
        ApprovalDecision.objects.create(
            approval_request=approval_request,
            actor=actor,
            channel=channel,
            decision=decision,
            reason=reason,
            metadata=decision_payload,
        )

        required_approvals = max(1, int(approval_request.required_approvals))
        approved_count = self._approved_count(approval_request=approval_request)

        if decision == DecisionType.REJECT:
            self._finalize_request(
                approval_request=approval_request,
                actor=actor,
                status="rejected",
                reason=reason or "Rejected by approver.",
            )
            self._reject_trade_intent(
                approval_request=approval_request,
                reason=reason or "Rejected by approver.",
            )
            return ApprovalDecisionOutcome(
                approval_request=approval_request,
                status=approval_request.status,
                is_final=True,
                approved_count=approved_count,
                required_approvals=required_approvals,
            )

        if approved_count >= required_approvals:
            self._finalize_request(
                approval_request=approval_request,
                actor=actor,
                status="approved",
                reason=reason,
            )
            self._approve_trade_intent(approval_request=approval_request)
            return ApprovalDecisionOutcome(
                approval_request=approval_request,
                status=approval_request.status,
                is_final=True,
                approved_count=approved_count,
                required_approvals=required_approvals,
            )

        approval_request.save(update_fields=["updated_at"])
        return ApprovalDecisionOutcome(
            approval_request=approval_request,
            status=approval_request.status,
            is_final=False,
            approved_count=approved_count,
            required_approvals=required_approvals,
        )

    def _finalize_request(
        self,
        *,
        approval_request: ApprovalRequest,
        actor: Any,
        status: str,
        reason: str,
    ) -> None:
        approval_request.decided_by = actor
        approval_request.decided_at = timezone.now()
        approval_request.decision_reason = reason
        approval_request.status = status
        approval_request.save(
            update_fields=[
                "decided_by",
                "decided_at",
                "decision_reason",
                "status",
                "updated_at",
            ]
        )

    @staticmethod
    def _approved_count(*, approval_request: ApprovalRequest) -> int:
        queryset: QuerySet[ApprovalDecision] = approval_request.decisions.filter(
            decision=DecisionType.APPROVE
        )
        return int(queryset.count())

    @staticmethod
    def _actor_has_decided(*, approval_request: ApprovalRequest, actor: Any) -> bool:
        if actor is None:
            return False
        return bool(approval_request.decisions.filter(actor=actor).exists())

    @staticmethod
    def _can_user_decide(*, approval_request: ApprovalRequest, actor: Any) -> bool:
        if actor is None:
            return False

        if bool(getattr(actor, "is_superuser", False)) or bool(getattr(actor, "is_staff", False)):
            return True

        if int(getattr(actor, "id", 0)) == approval_request.agent.owner_id:
            return True

        return bool(approval_request.agent.approvers.filter(id=actor.id).exists())

    @staticmethod
    def _approve_trade_intent(*, approval_request: ApprovalRequest) -> None:
        trade_intent = getattr(approval_request, "trade_intent", None)
        if trade_intent is None:
            return

        trade_intent.status = IntentStatus.APPROVED
        trade_intent.failure_reason = ""
        trade_intent.save(update_fields=["status", "failure_reason", "updated_at"])
        execute_intent_task.delay(trade_intent.id, True)

    @staticmethod
    def _reject_trade_intent(*, approval_request: ApprovalRequest, reason: str) -> None:
        trade_intent = getattr(approval_request, "trade_intent", None)
        if trade_intent is None:
            return

        trade_intent.status = IntentStatus.REJECTED
        trade_intent.failure_reason = reason
        trade_intent.save(update_fields=["status", "failure_reason", "updated_at"])

    @staticmethod
    def default_reason_for_channel(decision: str, channel: str) -> str:
        if channel == "telegram" and decision == DecisionType.APPROVE:
            return "Approved from Telegram."
        if channel == "telegram" and decision == DecisionType.REJECT:
            return "Rejected from Telegram."
        return ""
