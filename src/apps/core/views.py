from typing import Any

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: tuple[type, ...] = ()

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        configured: dict[str, bool] = {}
        for key in settings.REQUIRED_RUNTIME_SECRET_KEYS:
            configured[key] = str(getattr(settings, key, "")).strip() != ""
        return Response(
            {
                "status": "ok",
                "runtime_secrets": {
                    "required": list(settings.REQUIRED_RUNTIME_SECRET_KEYS),
                    "configured": configured,
                    "all_configured": all(configured.values()),
                },
            }
        )
