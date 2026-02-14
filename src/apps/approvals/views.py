from datetime import timedelta
from typing import Any, cast

from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.approvals.models import ApprovalRequest
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

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        due_soon_seconds = self.request.query_params.get("due_soon_seconds", "300")
        try:
            context["due_soon_seconds"] = max(1, int(due_soon_seconds))
        except ValueError:
            context["due_soon_seconds"] = 300
        return cast(dict[str, Any], context)

    def filter_queryset(self, queryset: QuerySet[ApprovalRequest]) -> QuerySet[ApprovalRequest]:
        queryset = super().filter_queryset(queryset)
        status_param = self.request.query_params.get("status")
        channel_param = self.request.query_params.get("channel")
        agent_id_param = self.request.query_params.get("agent_id")
        overdue_param = self.request.query_params.get("overdue")
        mine_only_param = self.request.query_params.get("mine_only")
        now = timezone.now()

        if status_param:
            queryset = queryset.filter(status=status_param)
        if channel_param:
            queryset = queryset.filter(channel=channel_param)
        if agent_id_param and agent_id_param.isdigit():
            queryset = queryset.filter(agent_id=int(agent_id_param))
        if overdue_param == "true":
            queryset = queryset.filter(
                status="pending",
                expires_at__isnull=False,
                expires_at__lt=now,
            )
        if overdue_param == "false":
            queryset = queryset.exclude(
                status="pending",
                expires_at__isnull=False,
                expires_at__lt=now,
            )
        if mine_only_param == "true":
            queryset = queryset.exclude(decisions__actor=self.request.user)

        return queryset.distinct()

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

    @action(detail=False, methods=["get"], url_path="queue")
    def queue(
        self,
        request: Request,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        queryset = self.filter_queryset(self.get_queryset()).filter(status="pending")
        due_soon_seconds = int(self.get_serializer_context()["due_soon_seconds"])

        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        now = timezone.now()
        overdue_count = queryset.filter(expires_at__isnull=False, expires_at__lt=now).count()
        due_soon_count = queryset.filter(
            expires_at__isnull=False,
            expires_at__gte=now,
            expires_at__lte=now + timedelta(seconds=due_soon_seconds),
        ).count()

        summary = {
            "pending_count": queryset.count(),
            "overdue_count": overdue_count,
            "due_soon_count": due_soon_count,
            "mine_pending_count": queryset.exclude(decisions__actor=request.user)
            .distinct()
            .count(),
        }
        return Response({"summary": summary, "results": data}, status=status.HTTP_200_OK)
