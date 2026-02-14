from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class RiskPolicy(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="risk_policies",
    )
    name = models.CharField(max_length=128)

    max_order_notional = models.DecimalField(max_digits=14, decimal_places=2, default=10000)
    max_position_notional = models.DecimalField(max_digits=14, decimal_places=2, default=100000)
    max_daily_loss = models.DecimalField(max_digits=14, decimal_places=2, default=2000)
    max_orders_per_day = models.PositiveIntegerField(default=20)

    allowed_symbols = models.JSONField(default=list, blank=True)
    require_market_hours = models.BooleanField(default=True)
    allow_shorting = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "name"),
                name="unique_risk_policy_name_per_owner",
            )
        ]
        indexes = [
            models.Index(fields=("owner", "is_default")),
            models.Index(fields=("is_default",)),
        ]

    def __str__(self) -> str:
        return f"{self.owner_id}:{self.name}"
