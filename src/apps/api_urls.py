from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.agents.views import AgentViewSet
from apps.approvals.telegram_views import TelegramWebhookView
from apps.approvals.views import ApprovalRequestViewSet
from apps.credentials.views import BrokerCredentialViewSet, LlmCredentialViewSet

router = DefaultRouter()
router.register(r"agents", AgentViewSet, basename="agent")
router.register(r"approval-requests", ApprovalRequestViewSet, basename="approval-request")
router.register(r"broker-credentials", BrokerCredentialViewSet, basename="broker-credential")
router.register(r"llm-credentials", LlmCredentialViewSet, basename="llm-credential")

urlpatterns = [
    path(
        "telegram/webhook/<str:webhook_secret>/",
        TelegramWebhookView.as_view(),
        name="telegram-webhook",
    ),
    path("", include(router.urls)),
]
