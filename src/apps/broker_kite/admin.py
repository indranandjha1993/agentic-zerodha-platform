from django.contrib import admin

from apps.broker_kite.models import KiteSession


@admin.register(KiteSession)
class KiteSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "kite_user_id",
        "session_expires_at",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = ("user__username", "kite_user_id")
