from django.contrib import admin

from apps.accounts.models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "telegram_chat_id", "timezone", "created_at")
    search_fields = ("=id", "^user__username", "user__email", "^telegram_chat_id")
    search_help_text = "Search by profile id, username/email, or Telegram chat id."
    list_select_related = ("user",)
    ordering = ("-created_at",)
