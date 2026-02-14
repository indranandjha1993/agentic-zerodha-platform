from django.http import HttpRequest, JsonResponse

from apps.core.services.admin_dashboard import build_admin_dashboard_snapshot


def control_tower_metrics_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse(build_admin_dashboard_snapshot())
