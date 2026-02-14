from typing import Any

from django.contrib import admin
from django.utils.html import format_html

from apps.approvals.models import ApprovalDecision, ApprovalRequest, TelegramCallbackEvent


def _status_chip(value: str) -> Any:
    normalized = value.lower()
    style_class = "warn"
    if normalized in {"approved"}:
        style_class = "ok"
    if normalized in {"rejected", "expired", "canceled"}:
        style_class = "err"
    return format_html('<span class="status-chip {}">{}</span>', style_class, value)


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agent",
        "channel",
        "status_badge",
        "required_approvals",
        "timeout_policy",
        "is_escalated",
        "requested_by",
        "decided_by",
        "expires_at",
        "updated_at",
    )
    list_filter = ("status", "channel", "timeout_policy", "is_escalated")
    search_fields = (
        "=id",
        "idempotency_key",
        "^agent__name",
        "^requested_by__username",
        "requested_by__email",
        "^decided_by__username",
        "decided_by__email",
        "notes",
        "decision_reason",
    )
    search_help_text = (
        "Search by request/idempotency key, agent, requester/decider, or decision notes."
    )
    list_select_related = ("agent", "requested_by", "decided_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj: ApprovalRequest) -> Any:
        return _status_chip(obj.status)


@admin.register(ApprovalDecision)
class ApprovalDecisionAdmin(admin.ModelAdmin):
    list_display = ("approval_request", "decision_badge", "channel", "actor", "created_at")
    list_filter = ("decision", "channel")
    search_fields = (
        "=id",
        "=approval_request__id",
        "^actor__username",
        "actor__email",
        "reason",
    )
    search_help_text = "Search by decision/request id, actor, or reason text."
    list_select_related = ("approval_request", "actor")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Decision", ordering="decision")
    def decision_badge(self, obj: ApprovalDecision) -> Any:
        if obj.decision == "approve":
            return format_html('<span class="status-chip ok">Approve</span>')
        return format_html('<span class="status-chip err">Reject</span>')


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
    search_fields = ("^callback_query_id", "^telegram_user_id", "=approval_request__id")
    search_help_text = "Search by callback query id, Telegram user id, or approval id."
    list_select_related = ("approval_request",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
