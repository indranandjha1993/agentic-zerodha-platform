from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class AuditLevel(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"


class AuditEvent(TimeStampedModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=64)
    level = models.CharField(max_length=16, choices=AuditLevel.choices, default=AuditLevel.INFO)

    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    payload = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("event_type", "created_at")),
            models.Index(fields=("level", "created_at")),
            models.Index(fields=("entity_type", "entity_id", "created_at")),
            models.Index(fields=("request_id", "created_at")),
            models.Index(fields=("actor", "created_at")),
        ]

    def __str__(self) -> str:
        return f"AuditEvent<{self.event_type}:{self.level}>"
