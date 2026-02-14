from django.db.models import QuerySet
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.credentials.models import BrokerCredential, LlmCredential
from apps.credentials.serializers import BrokerCredentialSerializer, LlmCredentialSerializer


class BrokerCredentialViewSet(ModelViewSet):
    serializer_class = BrokerCredentialSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[BrokerCredential]:
        return BrokerCredential.objects.filter(user=self.request.user).order_by("-updated_at")


class LlmCredentialViewSet(ModelViewSet):
    serializer_class = LlmCredentialSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[LlmCredential]:
        return LlmCredential.objects.filter(user=self.request.user).order_by("-updated_at")
