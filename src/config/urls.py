from django.contrib import admin
from django.urls import include, path

from apps.core.admin_views import control_tower_metrics_view
from apps.core.views import HealthCheckView

urlpatterns = [
    path(
        "admin/control-tower/metrics/",
        admin.site.admin_view(control_tower_metrics_view),
        name="admin-control-tower-metrics",
    ),
    path("admin/", admin.site.urls),
    path("health/", HealthCheckView.as_view(), name="health"),
    path("api/v1/", include("apps.api_urls")),
]
