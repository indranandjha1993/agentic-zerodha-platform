from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class BrokerType(models.TextChoices):
    KITE = "kite", "Zerodha Kite"


class LlmProvider(models.TextChoices):
    OPENROUTER = "openrouter", "OpenRouter"


class BrokerCredential(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broker_credentials",
    )
    broker = models.CharField(max_length=32, choices=BrokerType.choices, default=BrokerType.KITE)
    alias = models.CharField(max_length=64, default="default")

    api_key = models.CharField(max_length=255)
    api_secret_encrypted = models.TextField()
    access_token_encrypted = models.TextField(blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    access_token_expires_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    extra_config = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "broker", "alias"),
                name="unique_broker_credential_per_user_alias",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.broker}:{self.alias}"


class LlmCredential(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="llm_credentials",
    )
    provider = models.CharField(
        max_length=32,
        choices=LlmProvider.choices,
        default=LlmProvider.OPENROUTER,
    )
    api_key_encrypted = models.TextField()
    default_model = models.CharField(max_length=128, default="openai/gpt-4o-mini")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "provider"),
                name="unique_llm_credential_per_user_provider",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.provider}"
