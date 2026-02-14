from django.db.models import Q, QuerySet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.agents.models import Agent
from apps.agents.serializers import AgentAnalysisRequestSerializer, AgentSerializer
from apps.agents.services.openrouter_market_analyst import (
    MissingLlmCredentialError,
    OpenRouterAgentError,
    OpenRouterMarketAnalyst,
)
from apps.audit.models import AuditEvent, AuditLevel


class AgentViewSet(ModelViewSet):
    serializer_class = AgentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Agent]:
        return (
            Agent.objects.filter(Q(owner=self.request.user) | Q(approvers=self.request.user))
            .select_related("risk_policy")
            .prefetch_related("approvers")
            .distinct()
            .order_by("-updated_at")
        )

    def perform_update(self, serializer: AgentSerializer) -> None:
        agent = self.get_object()
        if agent.owner_id != self.request.user.id and not self.request.user.is_staff:
            raise PermissionDenied("Only the owner can update this agent.")
        serializer.save()

    def perform_destroy(self, instance: Agent) -> None:
        if instance.owner_id != self.request.user.id and not self.request.user.is_staff:
            raise PermissionDenied("Only the owner can delete this agent.")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="analyze")
    def analyze(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        agent = self.get_object()
        serializer = AgentAnalysisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        analyst = OpenRouterMarketAnalyst()
        try:
            result = analyst.analyze(
                agent=agent,
                user_query=serializer.validated_data["query"],
                model=serializer.validated_data.get("model") or None,
                max_steps=serializer.validated_data.get("max_steps"),
            )
        except MissingLlmCredentialError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OpenRouterAgentError as exc:
            AuditEvent.objects.create(
                actor=request.user,
                event_type="agent_market_analysis_failed",
                level=AuditLevel.ERROR,
                entity_type="agent",
                entity_id=str(agent.id),
                payload={"error": str(exc)},
                message="OpenRouter market analysis failed.",
            )
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        AuditEvent.objects.create(
            actor=request.user,
            event_type="agent_market_analysis_completed",
            level=AuditLevel.INFO,
            entity_type="agent",
            entity_id=str(agent.id),
            payload={
                "model": result.get("model"),
                "steps_executed": result.get("steps_executed"),
            },
            message="OpenRouter market analysis completed.",
        )
        return Response(result, status=status.HTTP_200_OK)
