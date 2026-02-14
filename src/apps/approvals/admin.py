from django.contrib import admin

from apps.approvals.models import ApprovalDecision, ApprovalRequest, TelegramCallbackEvent


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agent",
        "channel",
        "status",
        "required_approvals",
        "requested_by",
        "decided_by",
        "expires_at",
        "updated_at",
    )
    list_filter = ("status", "channel")
    search_fields = ("agent__name", "requested_by__username", "decided_by__username")


@admin.register(ApprovalDecision)
class ApprovalDecisionAdmin(admin.ModelAdmin):
    list_display = ("approval_request", "decision", "channel", "actor", "created_at")
    list_filter = ("decision", "channel")
    search_fields = ("approval_request__id", "actor__username")


@admin.register(TelegramCallbackEvent)
class TelegramCallbackEventAdmin(admin.ModelAdmin):
    list_display = (
        "callback_query_id",
        "approval_request",
        "telegram_user_id",
        "decision",
        "created_at",
    )
    list_filter = ("decision",)
    search_fields = ("callback_query_id", "telegram_user_id")
