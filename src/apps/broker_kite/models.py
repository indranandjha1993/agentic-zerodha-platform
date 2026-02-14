from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class KiteSession(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kite_sessions",
    )
    kite_user_id = models.CharField(max_length=64)
    public_token = models.CharField(max_length=255, blank=True)
    access_token_last4 = models.CharField(max_length=4, blank=True)
    session_expires_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"KiteSession<{self.user_id}:{self.kite_user_id}>"
