from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.approvals.models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    DecisionType,
)
from apps.approvals.serializers import ApprovalDecisionInputSerializer, ApprovalRequestSerializer


class ApprovalRequestViewSet(ReadOnlyModelViewSet):
    serializer_class = ApprovalRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[ApprovalRequest]:
        return (
            ApprovalRequest.objects.filter(agent__owner=self.request.user)
            .select_related("agent", "requested_by", "decided_by")
            .prefetch_related("decisions")
            .order_by("-created_at")
        )

    @action(detail=True, methods=["post"], url_path="decide")
    def decide(
        self,
        request: Request,
        pk: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        approval_request = self.get_object()

        serializer = ApprovalDecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if approval_request.status != ApprovalStatus.PENDING:
            return Response(
                {"detail": "Approval request is no longer pending."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        decision = serializer.validated_data["decision"]
        reason = serializer.validated_data.get("reason", "")
        channel = serializer.validated_data["channel"]

        ApprovalDecision.objects.create(
            approval_request=approval_request,
            actor=request.user,
            channel=channel,
            decision=decision,
            reason=reason,
        )

        approval_request.decided_by = request.user
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

        response_data = ApprovalRequestSerializer(approval_request).data
        return Response(response_data, status=status.HTTP_200_OK)
