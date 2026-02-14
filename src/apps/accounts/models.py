from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class UserProfile(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    telegram_chat_id = models.CharField(max_length=64, blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")

    def __str__(self) -> str:
        return f"Profile<{self.user_id}>"
