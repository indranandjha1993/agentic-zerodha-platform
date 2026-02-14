from datetime import UTC, datetime
from typing import Any

from apps.execution.models import TradeIntent

try:
    from kiteconnect import KiteConnect
except Exception:  # pragma: no cover
    KiteConnect = None


class KiteAdapter:
    def __init__(self, api_key: str | None = None, access_token: str | None = None) -> None:
        self.api_key = api_key
        self.access_token = access_token

    def _build_client(self) -> Any:
        if KiteConnect is None:
            raise RuntimeError("pykiteconnect is not available in the runtime environment.")

        if not self.api_key or not self.access_token:
            raise RuntimeError("Kite API credentials are missing.")

        client = KiteConnect(api_key=self.api_key)
        client.set_access_token(self.access_token)
        return client

    def place_order(self, intent: TradeIntent) -> dict[str, Any]:
        if not self.api_key or not self.access_token:
            # Safe fallback for local scaffolding before credential wiring.
            return {
                "order_id": f"sim-{intent.id}",
                "status": "simulated",
                "placed_at": datetime.now(UTC).isoformat(),
            }

        client = self._build_client()
        order_id = client.place_order(
            variety="regular",
            exchange=intent.exchange,
            tradingsymbol=intent.symbol,
            transaction_type=intent.side,
            quantity=intent.quantity,
            product=intent.product,
            order_type=intent.order_type,
            price=float(intent.price) if intent.price is not None else None,
            trigger_price=float(intent.trigger_price) if intent.trigger_price is not None else None,
        )
        return {"order_id": order_id, "status": "placed"}
