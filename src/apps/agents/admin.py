from django.contrib import admin

from apps.agents.models import Agent


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "status",
        "execution_mode",
        "approval_mode",
        "required_approvals",
        "is_auto_enabled",
        "updated_at",
    )
    list_filter = ("status", "execution_mode", "approval_mode", "is_auto_enabled")
    search_fields = ("name", "slug", "owner__username", "owner__email")
    filter_horizontal = ("approvers",)
