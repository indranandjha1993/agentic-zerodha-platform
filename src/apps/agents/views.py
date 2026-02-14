from django.db.models import Q, QuerySet
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.agents.models import Agent
from apps.agents.serializers import AgentSerializer


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
