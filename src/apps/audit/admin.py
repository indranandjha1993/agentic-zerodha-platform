from django.contrib import admin

from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "level", "entity_type", "entity_id", "actor", "created_at")
    list_filter = ("level", "event_type")
    search_fields = (
        "=id",
        "^event_type",
        "^entity_type",
        "^entity_id",
        "^request_id",
        "^actor__username",
        "actor__email",
        "message",
    )
    search_help_text = "Search by event id/type, entity/request id, actor, or message text."
    list_select_related = ("actor",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
