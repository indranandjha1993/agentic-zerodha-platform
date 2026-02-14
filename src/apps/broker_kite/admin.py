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
    search_fields = (
        "=id",
        "^user__username",
        "user__email",
        "^kite_user_id",
        "^access_token_last4",
    )
    search_help_text = "Search by session id, user identity, Kite user id, or token suffix."
    list_select_related = ("user",)
    ordering = ("-updated_at",)
