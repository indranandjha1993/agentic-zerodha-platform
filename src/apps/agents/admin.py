from django.contrib import admin

from apps.agents.models import (
    Agent,
    AgentAnalysisEvent,
    AgentAnalysisNotificationDelivery,
    AgentAnalysisRun,
    AgentAnalysisWebhookEndpoint,
)


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "status",
        "execution_mode",
        "approval_mode",
        "required_approvals",
        "is_auto_enabled",
        "updated_at",
    )
    list_filter = ("status", "execution_mode", "approval_mode", "is_auto_enabled")
    search_fields = ("name", "slug", "owner__username", "owner__email")
    filter_horizontal = ("approvers",)


@admin.register(AgentAnalysisRun)
class AgentAnalysisRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agent",
        "requested_by",
        "status",
        "model",
        "steps_executed",
        "started_at",
        "completed_at",
    )
    list_filter = ("status",)
    search_fields = ("agent__name", "requested_by__username", "query", "model")


@admin.register(AgentAnalysisEvent)
class AgentAnalysisEventAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "sequence", "event_type", "created_at")
    list_filter = ("event_type",)
    search_fields = ("run__id", "event_type")


@admin.register(AgentAnalysisWebhookEndpoint)
class AgentAnalysisWebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "name", "callback_url", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "owner__username", "owner__email", "callback_url")


@admin.register(AgentAnalysisNotificationDelivery)
class AgentAnalysisNotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "endpoint",
        "run",
        "event_type",
        "success",
        "attempt_count",
        "max_attempts",
        "status_code",
        "next_retry_at",
        "created_at",
    )
    list_filter = ("event_type", "success")
    search_fields = ("run__id", "endpoint__name", "error_message")
