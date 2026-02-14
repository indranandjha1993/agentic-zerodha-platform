from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.agents.views import AgentAnalysisWebhookEndpointViewSet, AgentViewSet
from apps.approvals.telegram_views import TelegramWebhookView
from apps.approvals.views import ApprovalRequestViewSet

router = DefaultRouter()
router.register(r"agents", AgentViewSet, basename="agent")
router.register(
    r"analysis-webhook-endpoints",
    AgentAnalysisWebhookEndpointViewSet,
    basename="analysis-webhook-endpoint",
)
router.register(r"approval-requests", ApprovalRequestViewSet, basename="approval-request")

urlpatterns = [
    path(
        "telegram/webhook/<str:webhook_secret>/",
        TelegramWebhookView.as_view(),
        name="telegram-webhook",
    ),
    path("", include(router.urls)),
]
