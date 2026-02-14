import uuid
from decimal import Decimal

from django.db import models

from apps.core.models import TimeStampedModel


class IntentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending Approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    QUEUED = "queued", "Queued"
    PLACED = "placed", "Placed"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"


class Side(models.TextChoices):
    BUY = "BUY", "Buy"
    SELL = "SELL", "Sell"


class OrderType(models.TextChoices):
    MARKET = "MARKET", "Market"
    LIMIT = "LIMIT", "Limit"
    SL = "SL", "Stop Loss"
    SLM = "SL-M", "Stop Loss Market"


class ProductType(models.TextChoices):
    MIS = "MIS", "MIS"
    CNC = "CNC", "CNC"
    NRML = "NRML", "NRML"


class TradeIntent(TimeStampedModel):
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    agent = models.ForeignKey(
        "agents.Agent",
        on_delete=models.CASCADE,
        related_name="trade_intents",
    )
    approval_request = models.OneToOneField(
        "approvals.ApprovalRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trade_intent",
    )

    symbol = models.CharField(max_length=64)
    exchange = models.CharField(max_length=16, default="NSE")
    side = models.CharField(max_length=8, choices=Side.choices)
    quantity = models.PositiveIntegerField()

    order_type = models.CharField(
        max_length=16,
        choices=OrderType.choices,
        default=OrderType.MARKET,
    )
    product = models.CharField(
        max_length=16,
        choices=ProductType.choices,
        default=ProductType.MIS,
    )

    price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    trigger_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    notional_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    status = models.CharField(
        max_length=32,
        choices=IntentStatus.choices,
        default=IntentStatus.DRAFT,
    )
    broker_order_id = models.CharField(max_length=128, blank=True)

    request_payload = models.JSONField(default=dict, blank=True)
    broker_response = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True)

    placed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("status", "created_at")),
            models.Index(fields=("agent", "created_at")),
            models.Index(fields=("symbol", "created_at")),
            models.Index(fields=("broker_order_id",)),
            models.Index(fields=("placed_at",)),
        ]

    def save(self, *args: object, **kwargs: object) -> None:
        if self.price is not None and self.quantity:
            self.notional_value = Decimal(self.price) * Decimal(self.quantity)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Intent<{self.id}>:{self.symbol}:{self.side}:{self.status}"
