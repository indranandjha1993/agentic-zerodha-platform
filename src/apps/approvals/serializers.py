from typing import cast

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
            "approved_count",
            "pending_approvals",
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
