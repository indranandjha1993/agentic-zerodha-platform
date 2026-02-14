from django.contrib import admin

from apps.execution.models import TradeIntent


@admin.register(TradeIntent)
class TradeIntentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agent",
        "symbol",
        "side",
        "quantity",
        "status",
        "broker_order_id",
        "created_at",
    )
    list_filter = ("status", "side", "exchange", "order_type", "product")
    search_fields = ("symbol", "broker_order_id", "agent__name")
