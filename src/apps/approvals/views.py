from typing import Any

from django.db.models import Q, QuerySet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.approvals.models import (
    ApprovalRequest,
)
from apps.approvals.serializers import ApprovalDecisionInputSerializer, ApprovalRequestSerializer
from apps.approvals.services.decision_engine import (
    ApprovalDecisionConflictError,
    ApprovalDecisionDuplicateError,
    ApprovalDecisionPermissionError,
    ApprovalDecisionService,
)


class ApprovalRequestViewSet(ReadOnlyModelViewSet):
    serializer_class = ApprovalRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[ApprovalRequest]:
        user = self.request.user
        return (
            ApprovalRequest.objects.filter(Q(agent__owner=user) | Q(agent__approvers=user))
            .select_related("agent", "requested_by", "decided_by")
            .prefetch_related("decisions")
            .distinct()
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

        decision = serializer.validated_data["decision"]
        reason = serializer.validated_data.get("reason", "")
        channel = serializer.validated_data["channel"]

        decision_service = ApprovalDecisionService()
        try:
            outcome = decision_service.decide(
                approval_request=approval_request,
                actor=request.user,
                decision=decision,
                channel=channel,
                reason=reason,
            )
        except ApprovalDecisionConflictError:
            return Response(
                {"detail": "Approval request is no longer pending."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ApprovalDecisionPermissionError:
            return Response(
                {"detail": "You are not allowed to decide this request."},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ApprovalDecisionDuplicateError:
            return Response(
                {"detail": "You have already decided this request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_data = ApprovalRequestSerializer(approval_request).data
        response_data["decision_outcome"] = {
            "is_final": outcome.is_final,
            "approved_count": outcome.approved_count,
            "required_approvals": outcome.required_approvals,
        }
        return Response(response_data, status=status.HTTP_200_OK)
