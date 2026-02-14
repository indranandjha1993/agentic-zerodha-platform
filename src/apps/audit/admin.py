from django.contrib import admin

from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "level", "entity_type", "entity_id", "actor", "created_at")
    list_filter = ("level", "event_type")
    search_fields = ("event_type", "entity_type", "entity_id", "actor__username")
