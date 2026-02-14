from typing import Any
from urllib.parse import urlparse

from django import template

from apps.core.services.admin_dashboard import build_admin_dashboard_snapshot

register = template.Library()

GROUP_DEFINITIONS = (
    {
        "id": "trading",
        "title": "Trading Core",
        "description": "Agent lifecycle, risk controls, approvals, execution, and market feeds.",
        "labels": {"agents", "approvals", "execution", "risk", "market_data", "broker_kite"},
    },
    {
        "id": "operations",
        "title": "Operations",
        "description": "Account state, audit telemetry, and platform governance.",
        "labels": {"accounts", "audit"},
    },
    {
        "id": "platform",
        "title": "Django Platform",
        "description": "Built-in admin/auth models and framework internals.",
        "labels": {"auth", "admin", "contenttypes", "sessions"},
    },
)


@register.simple_tag
def get_admin_dashboard_snapshot() -> dict[str, object]:
    return build_admin_dashboard_snapshot()


@register.filter
def metric_value(metrics: dict[str, Any], key: str) -> Any:
    return metrics.get(key, 0)


def _normalize_app_label(app: dict[str, Any]) -> str:
    label = app.get("app_label")
    if label:
        return str(label)

    app_url = app.get("app_url")
    if not app_url:
        return ""
    path = urlparse(str(app_url)).path.strip("/")
    if not path:
        return ""
    parts = path.split("/")
    if "admin" in parts:
        admin_index = parts.index("admin")
        if admin_index + 1 < len(parts):
            return parts[admin_index + 1]
    return parts[-1]


@register.simple_tag
def get_grouped_admin_apps(app_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    app_buckets: dict[str, list[dict[str, Any]]] = {
        str(definition["id"]): [] for definition in GROUP_DEFINITIONS
    }
    app_buckets["other"] = []

    for app in app_list:
        app_label = _normalize_app_label(app)
        target_group_id = "other"
        for definition in GROUP_DEFINITIONS:
            if app_label in set(definition["labels"]):
                target_group_id = str(definition["id"])
                break
        app_buckets[target_group_id].append(app)

    grouped_apps: list[dict[str, Any]] = []
    for definition in GROUP_DEFINITIONS:
        group_id = str(definition["id"])
        apps = app_buckets[group_id]
        if not apps:
            continue
        sorted_apps = sorted(apps, key=lambda item: str(item.get("name", "")))
        model_count = sum(len(item.get("models", [])) for item in sorted_apps)
        grouped_apps.append(
            {
                "id": group_id,
                "title": definition["title"],
                "description": definition["description"],
                "apps": sorted_apps,
                "app_count": len(sorted_apps),
                "model_count": model_count,
            }
        )

    other_apps = app_buckets["other"]
    if other_apps:
        sorted_other_apps = sorted(other_apps, key=lambda item: str(item.get("name", "")))
        other_model_count = sum(len(item.get("models", [])) for item in sorted_other_apps)
        grouped_apps.append(
            {
                "id": "other",
                "title": "Other Modules",
                "description": (
                    "Additional admin modules that do not map to primary platform groups."
                ),
                "apps": sorted_other_apps,
                "app_count": len(sorted_other_apps),
                "model_count": other_model_count,
            }
        )

    return grouped_apps
