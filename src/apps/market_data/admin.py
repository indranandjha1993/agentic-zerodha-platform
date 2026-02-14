from django.contrib import admin

from apps.market_data.models import Instrument, TickSnapshot


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = (
        "tradingsymbol",
        "exchange",
        "segment",
        "instrument_type",
        "is_active",
        "updated_at",
    )
    list_filter = ("exchange", "segment", "instrument_type", "is_active")
    search_fields = ("=instrument_token", "^tradingsymbol", "^name", "^exchange", "^segment")
    search_help_text = "Search by instrument token, symbol/name, exchange, or segment."
    ordering = ("exchange", "tradingsymbol")


@admin.register(TickSnapshot)
class TickSnapshotAdmin(admin.ModelAdmin):
    list_display = ("instrument", "last_price", "volume", "oi", "source", "created_at")
    list_filter = ("source",)
    search_fields = (
        "=id",
        "=instrument__instrument_token",
        "^instrument__tradingsymbol",
        "^source",
    )
    search_help_text = "Search by tick id, instrument token/symbol, or source."
    list_select_related = ("instrument",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
