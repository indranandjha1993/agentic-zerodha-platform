from django.db.models import QuerySet
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.agents.models import Agent
from apps.agents.serializers import AgentSerializer


class AgentViewSet(ModelViewSet):
    serializer_class = AgentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Agent]:
        return (
            Agent.objects.filter(owner=self.request.user)
            .select_related("risk_policy")
            .order_by("-updated_at")
        )
