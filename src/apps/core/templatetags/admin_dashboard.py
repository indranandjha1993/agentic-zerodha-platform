from typing import Any

from django import template

from apps.core.services.admin_dashboard import build_admin_dashboard_snapshot

register = template.Library()


@register.simple_tag
def get_admin_dashboard_snapshot() -> dict[str, object]:
    return build_admin_dashboard_snapshot()


@register.filter
def metric_value(metrics: dict[str, Any], key: str) -> Any:
    return metrics.get(key, 0)
