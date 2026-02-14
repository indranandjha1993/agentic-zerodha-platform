from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.agents.models import AgentStatus
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


@dataclass(slots=True)
class ApprovalTimeoutOutcome:
    approval_request: ApprovalRequest
    action: str
    is_final: bool


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

    def apply_timeout_policy(
        self,
        *,
        approval_request: ApprovalRequest,
        current_time: Any | None = None,
    ) -> ApprovalTimeoutOutcome:
        if approval_request.status != "pending":
            return ApprovalTimeoutOutcome(
                approval_request=approval_request,
                action="skipped_non_pending",
                is_final=False,
            )

        now = current_time or timezone.now()
        policy = str(approval_request.timeout_policy)
        default_reason = "Approval request expired without required approvals."

        if policy == "auto_pause":
            self._record_system_decision(
                approval_request=approval_request,
                decision="reject",
                reason="Approval expired. Agent paused automatically.",
                metadata={"source": "timeout_policy", "policy": "auto_pause"},
            )
            self._finalize_request(
                approval_request=approval_request,
                actor=None,
                status="expired",
                reason="Approval expired and agent was auto-paused.",
            )
            approval_request.agent.status = AgentStatus.PAUSED
            approval_request.agent.is_auto_enabled = False
            approval_request.agent.save(update_fields=["status", "is_auto_enabled", "updated_at"])
            self._reject_trade_intent(
                approval_request=approval_request,
                reason="Approval expired and agent was auto-paused.",
            )
            return ApprovalTimeoutOutcome(
                approval_request=approval_request,
                action="auto_paused",
                is_final=True,
            )

        if policy == "escalate":
            if not approval_request.is_escalated:
                grace_minutes = max(
                    1,
                    int(approval_request.agent.config.get("escalation_grace_minutes", 15)),
                )
                approval_request.is_escalated = True
                approval_request.escalated_at = now
                approval_request.expires_at = now + timedelta(minutes=grace_minutes)
                approval_request.notes = self._append_note(
                    original=approval_request.notes,
                    note=(
                        "Escalated due to timeout. "
                        f"Waiting for admin decision for {grace_minutes} more minutes."
                    ),
                )
                approval_request.save(
                    update_fields=[
                        "is_escalated",
                        "escalated_at",
                        "expires_at",
                        "notes",
                        "updated_at",
                    ]
                )
                return ApprovalTimeoutOutcome(
                    approval_request=approval_request,
                    action="escalated",
                    is_final=False,
                )

            self._record_system_decision(
                approval_request=approval_request,
                decision="reject",
                reason="Escalated approval expired without decision.",
                metadata={"source": "timeout_policy", "policy": "escalate"},
            )
            self._finalize_request(
                approval_request=approval_request,
                actor=None,
                status="rejected",
                reason="Escalated approval expired without decision.",
            )
            self._reject_trade_intent(
                approval_request=approval_request,
                reason="Escalated approval expired without decision.",
            )
            return ApprovalTimeoutOutcome(
                approval_request=approval_request,
                action="escalation_expired_rejected",
                is_final=True,
            )

        self._record_system_decision(
            approval_request=approval_request,
            decision="reject",
            reason=default_reason,
            metadata={"source": "timeout_policy", "policy": "auto_reject"},
        )
        self._finalize_request(
            approval_request=approval_request,
            actor=None,
            status="rejected",
            reason=default_reason,
        )
        self._reject_trade_intent(approval_request=approval_request, reason=default_reason)
        return ApprovalTimeoutOutcome(
            approval_request=approval_request,
            action="auto_rejected",
            is_final=True,
        )

    @staticmethod
    def _record_system_decision(
        *,
        approval_request: ApprovalRequest,
        decision: str,
        reason: str,
        metadata: dict[str, Any],
    ) -> None:
        ApprovalDecision.objects.create(
            approval_request=approval_request,
            actor=None,
            channel="admin",
            decision=decision,
            reason=reason,
            metadata=metadata,
        )

    @staticmethod
    def _append_note(*, original: str, note: str) -> str:
        if original.strip() == "":
            return note
        return f"{original.rstrip()}\n{note}"

    @staticmethod
    def default_reason_for_channel(decision: str, channel: str) -> str:
        if channel == "telegram" and decision == DecisionType.APPROVE:
            return "Approved from Telegram."
        if channel == "telegram" and decision == DecisionType.REJECT:
            return "Rejected from Telegram."
        return ""
