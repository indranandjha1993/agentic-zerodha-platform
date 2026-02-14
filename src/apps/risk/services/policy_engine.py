from dataclasses import dataclass
from decimal import Decimal

from apps.execution.models import TradeIntent
from apps.risk.models import RiskPolicy


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reason: str
    risk_score: int


class RiskPolicyEngine:
    def evaluate(self, intent: TradeIntent, policy: RiskPolicy | None) -> RiskDecision:
        if policy is None:
            return RiskDecision(approved=True, reason="No policy configured.", risk_score=10)

        notional = intent.notional_value or Decimal("0")
        if notional > policy.max_order_notional:
            return RiskDecision(
                approved=False,
                reason="Order notional exceeds max_order_notional.",
                risk_score=95,
            )

        if policy.allowed_symbols and intent.symbol not in policy.allowed_symbols:
            return RiskDecision(
                approved=False,
                reason="Symbol not present in allowed_symbols.",
                risk_score=90,
            )

        return RiskDecision(approved=True, reason="Risk checks passed.", risk_score=20)
