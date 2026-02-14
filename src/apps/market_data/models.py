from django.db import models

from apps.core.models import TimeStampedModel


class Instrument(TimeStampedModel):
    instrument_token = models.BigIntegerField(unique=True)
    tradingsymbol = models.CharField(max_length=64)
    exchange = models.CharField(max_length=16)
    name = models.CharField(max_length=128, blank=True)
    segment = models.CharField(max_length=32, blank=True)
    instrument_type = models.CharField(max_length=32, blank=True)

    expiry = models.DateField(null=True, blank=True)
    strike = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    lot_size = models.PositiveIntegerField(default=1)
    tick_size = models.DecimalField(max_digits=10, decimal_places=4, default=0.05)

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tradingsymbol", "exchange", "segment"),
                name="unique_symbol_exchange_segment",
            )
        ]
        indexes = [
            models.Index(fields=("exchange", "tradingsymbol")),
            models.Index(fields=("is_active", "exchange")),
            models.Index(fields=("name",)),
        ]

    def __str__(self) -> str:
        return f"{self.exchange}:{self.tradingsymbol}"


class TickSnapshot(TimeStampedModel):
    instrument = models.ForeignKey(
        Instrument,
        on_delete=models.CASCADE,
        related_name="ticks",
    )
    last_price = models.DecimalField(max_digits=14, decimal_places=2)
    volume = models.BigIntegerField(default=0)
    oi = models.BigIntegerField(null=True, blank=True)
    source = models.CharField(max_length=32, default="kite_ticker")

    class Meta:
        indexes = [
            models.Index(fields=("instrument", "created_at")),
            models.Index(fields=("source", "created_at")),
        ]

    def __str__(self) -> str:
        return f"Tick<{self.instrument_id}:{self.last_price}>"
