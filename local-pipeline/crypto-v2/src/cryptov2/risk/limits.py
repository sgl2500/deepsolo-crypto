from __future__ import annotations

from dataclasses import dataclass

from cryptov2.data.schemas import OrderIntent


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str


@dataclass(slots=True)
class BasicRiskLimits:
    max_positions: int
    max_same_symbol_positions: int = 1

    def check(self, order: OrderIntent, active_symbols: list[str]) -> RiskDecision:
        if len(active_symbols) >= self.max_positions:
            return RiskDecision(False, "max_positions")
        if active_symbols.count(order.inst_id) >= self.max_same_symbol_positions:
            return RiskDecision(False, "same_symbol_position")
        return RiskDecision(True, "ok")
