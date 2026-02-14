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
    search_fields = ("tradingsymbol", "name", "instrument_token")


@admin.register(TickSnapshot)
class TickSnapshotAdmin(admin.ModelAdmin):
    list_display = ("instrument", "last_price", "volume", "oi", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("instrument__tradingsymbol",)
