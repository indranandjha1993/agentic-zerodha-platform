from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.agents.views import AgentViewSet
from apps.approvals.views import ApprovalRequestViewSet

router = DefaultRouter()
router.register(r"agents", AgentViewSet, basename="agent")
router.register(r"approval-requests", ApprovalRequestViewSet, basename="approval-request")

urlpatterns = [
    path("", include(router.urls)),
]
