from django.contrib import admin

from apps.accounts.models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "telegram_chat_id", "timezone", "created_at")
    search_fields = ("user__username", "user__email", "telegram_chat_id")
