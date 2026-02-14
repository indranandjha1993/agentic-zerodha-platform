from typing import cast

from django.utils import timezone
from rest_framework import serializers

from apps.approvals.models import (
    ApprovalChannel,
    ApprovalDecision,
    ApprovalRequest,
    DecisionType,
)


class ApprovalDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalDecision
        fields = ["id", "decision", "channel", "reason", "actor", "created_at"]


class ApprovalRequestSerializer(serializers.ModelSerializer):
    decisions = ApprovalDecisionSerializer(many=True, read_only=True)
    approved_count = serializers.SerializerMethodField()
    pending_approvals = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    seconds_to_expiry = serializers.SerializerMethodField()
    queue_bucket = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "idempotency_key",
            "agent",
            "requested_by",
            "channel",
            "status",
            "required_approvals",
            "timeout_policy",
            "is_escalated",
            "escalated_at",
            "approved_count",
            "pending_approvals",
            "is_overdue",
            "seconds_to_expiry",
            "queue_bucket",
            "intent_payload",
            "risk_snapshot",
            "notes",
            "expires_at",
            "decided_at",
            "decided_by",
            "decision_reason",
            "decisions",
            "created_at",
            "updated_at",
        ]

    def get_approved_count(self, obj: ApprovalRequest) -> int:
        return cast(int, obj.decisions.filter(decision=DecisionType.APPROVE).count())

    def get_pending_approvals(self, obj: ApprovalRequest) -> int:
        approved_count = self.get_approved_count(obj)
        remaining = int(obj.required_approvals) - approved_count
        return remaining if remaining > 0 else 0

    def get_is_overdue(self, obj: ApprovalRequest) -> bool:
        if obj.expires_at is None:
            return False
        if obj.status != "pending":
            return False
        return bool(obj.expires_at <= timezone.now())

    def get_seconds_to_expiry(self, obj: ApprovalRequest) -> int | None:
        if obj.expires_at is None:
            return None
        now = timezone.now()
        delta = obj.expires_at - now
        return int(delta.total_seconds())

    def get_queue_bucket(self, obj: ApprovalRequest) -> str:
        if obj.status != "pending":
            return "closed"

        seconds_to_expiry = self.get_seconds_to_expiry(obj)
        if seconds_to_expiry is None:
            return "no_expiry"
        if seconds_to_expiry < 0:
            return "overdue"

        due_soon_seconds = int(self.context.get("due_soon_seconds", 300))
        if seconds_to_expiry <= due_soon_seconds:
            return "due_soon"
        return "normal"


class ApprovalDecisionInputSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=(
            DecisionType.APPROVE,
            DecisionType.REJECT,
        )
    )
    reason = serializers.CharField(required=False, allow_blank=True)
    channel = serializers.ChoiceField(
        choices=(
            ApprovalChannel.DASHBOARD,
            ApprovalChannel.ADMIN,
            ApprovalChannel.TELEGRAM,
        ),
        default=ApprovalChannel.DASHBOARD,
    )
