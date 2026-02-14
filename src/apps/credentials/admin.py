from django.contrib import admin

from apps.credentials.models import BrokerCredential, LlmCredential


@admin.register(BrokerCredential)
class BrokerCredentialAdmin(admin.ModelAdmin):
    list_display = ("user", "broker", "alias", "is_active", "access_token_expires_at")
    list_filter = ("broker", "is_active")
    search_fields = ("user__username", "user__email", "alias", "api_key")


@admin.register(LlmCredential)
class LlmCredentialAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "default_model", "is_active", "updated_at")
    list_filter = ("provider", "is_active")
    search_fields = ("user__username", "user__email", "default_model")
