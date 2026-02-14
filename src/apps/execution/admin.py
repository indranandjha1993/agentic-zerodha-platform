from typing import Any

from django.contrib import admin
from django.utils.html import format_html

from apps.execution.models import TradeIntent


@admin.register(TradeIntent)
class TradeIntentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agent",
        "symbol",
        "side",
        "quantity",
        "status_badge",
        "broker_order_id",
        "placed_at",
        "created_at",
    )
    list_filter = ("status", "side", "exchange", "order_type", "product")
    search_fields = (
        "=id",
        "idempotency_key",
        "^symbol",
        "^broker_order_id",
        "^agent__name",
        "failure_reason",
    )
    search_help_text = "Search by intent id/key, symbol/order id, agent, or failure reason."
    list_select_related = ("agent", "approval_request")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj: TradeIntent) -> Any:
        normalized = obj.status.lower()
        style_class = "warn"
        if normalized in {"placed", "approved"}:
            style_class = "ok"
        if normalized in {"failed", "rejected", "canceled"}:
            style_class = "err"
        return format_html(
            '<span class="status-chip {}">{}</span>',
            style_class,
            obj.status,
        )
