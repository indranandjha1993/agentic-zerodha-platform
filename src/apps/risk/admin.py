from django.contrib import admin

from apps.risk.models import RiskPolicy


@admin.register(RiskPolicy)
class RiskPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "max_order_notional",
        "max_daily_loss",
        "max_orders_per_day",
        "is_default",
    )
    list_filter = ("is_default", "require_market_hours", "allow_shorting")
    search_fields = ("name", "owner__username", "owner__email")
