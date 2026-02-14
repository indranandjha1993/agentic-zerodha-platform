from typing import Any

from django.contrib import admin
from django.utils.html import format_html

from apps.agents.models import (
    Agent,
    AgentAnalysisEvent,
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
)


def _status_chip(value: str) -> Any:
    normalized = value.lower()
    style_class = "warn"
    if normalized in {"active", "completed", "approved", "placed", "true"}:
        style_class = "ok"
    if normalized in {"failed", "rejected", "canceled", "expired", "error"}:
        style_class = "err"
    return format_html('<span class="status-chip {}">{}</span>', style_class, value)


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "status_badge",
        "execution_mode",
        "approval_mode",
        "required_approvals",
        "is_auto_enabled",
        "last_run_at",
        "updated_at",
    )
    list_filter = ("status", "execution_mode", "approval_mode", "is_auto_enabled")
    search_fields = ("=id", "^name", "^slug", "^owner__username", "owner__email")
    search_help_text = "Search by exact agent id, name/slug prefix, or owner username/email."
    filter_horizontal = ("approvers",)
    list_select_related = ("owner", "risk_policy")
    date_hierarchy = "updated_at"
    ordering = ("-updated_at",)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj: Agent) -> Any:
        return _status_chip(obj.status)


@admin.register(AgentAnalysisRun)
class AgentAnalysisRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agent",
        "requested_by",
        "status_badge",
        "model",
        "steps_executed",
        "started_at",
        "completed_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "=id",
        "=agent__id",
        "^agent__name",
        "^requested_by__username",
        "requested_by__email",
        "model",
        "query",
        "error_message",
    )
    search_help_text = (
        "Search by run/agent id, agent or requestor, model, query text, or error message."
    )
    list_select_related = ("agent", "requested_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj: AgentAnalysisRun) -> Any:
        return _status_chip(obj.status)


@admin.register(AgentAnalysisEvent)
class AgentAnalysisEventAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "sequence", "event_type", "created_at")
    list_filter = ("event_type",)
    search_fields = ("=id", "=run__id", "^event_type")
    search_help_text = "Search by exact event/run id or event type prefix."
    list_select_related = ("run",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(AgentAnalysisWebhookEndpoint)
class AgentAnalysisWebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "name", "callback_url", "is_active", "has_secret", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("=id", "^name", "^owner__username", "owner__email", "callback_url")
    search_help_text = "Search by endpoint id/name, callback URL, or owner identity."
    list_select_related = ("owner",)
    date_hierarchy = "updated_at"
    ordering = ("-updated_at",)

    @admin.display(description="Signing Secret")
    def has_secret(self, obj: AgentAnalysisWebhookEndpoint) -> Any:
        if obj.signing_secret_encrypted:
            return format_html('<span class="status-chip ok">Configured</span>')
        return format_html('<span class="status-chip warn">Not Set</span>')


@admin.register(AgentAnalysisNotificationDelivery)
class AgentAnalysisNotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "endpoint",
        "run",
        "event_type",
        "success_badge",
        "attempt_count",
        "max_attempts",
        "status_code",
        "last_attempt_at",
        "next_retry_at",
        "created_at",
    )
    list_filter = ("event_type", "success")
    search_fields = (
        "=id",
        "=run__id",
        "^endpoint__name",
        "^event_type",
        "error_message",
        "response_body",
    )
    search_help_text = "Search by delivery/run id, endpoint, event type, or response/error text."
    list_select_related = ("endpoint", "run")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "endpoint",
        "run",
        "event_type",
        "success",
        "status_code",
        "attempt_count",
        "max_attempts",
        "last_attempt_at",
        "next_retry_at",
        "delivered_at",
        "request_payload",
        "response_body",
        "error_message",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Delivery")
    def success_badge(self, obj: AgentAnalysisNotificationDelivery) -> Any:
        if obj.success:
            return format_html('<span class="status-chip ok">Success</span>')
        if obj.next_retry_at is not None and obj.attempt_count < obj.max_attempts:
            return format_html('<span class="status-chip warn">Retrying</span>')
        return format_html('<span class="status-chip err">Failed</span>')
