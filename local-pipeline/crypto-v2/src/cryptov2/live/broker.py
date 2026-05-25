from __future__ import annotations

from abc import ABC, abstractmethod

from cryptov2.data.schemas import Fill, OrderIntent, Position


class Broker(ABC):
    @abstractmethod
    def place_order(self, order: OrderIntent) -> Fill:
        """Submit an order and return the fill result."""

    @abstractmethod
    def close_position(self, position: Position, reason: str) -> Fill:
        """Close an existing position."""

    @abstractmethod
    def positions(self) -> list[Position]:
        """Fetch current exchange positions."""


class PaperBroker(Broker):
    """Non-trading broker used for live dry runs."""

    def __init__(self):
        self._positions: list[Position] = []

    def place_order(self, order: OrderIntent) -> Fill:
        return Fill(
            strategy=order.strategy,
            inst_id=order.inst_id,
            side=order.side,
            position_side=order.position_side,
            ts=order.ts,
            price=order.ref_price,
            notional_usd=order.notional_usd,
            fee_usd=0.0,
            reason=order.reason,
            attrs=order.attrs,
        )

    def close_position(self, position: Position, reason: str) -> Fill:
        return Fill(
            strategy=position.strategy,
            inst_id=position.inst_id,
            side="buy" if position.side == "short" else "sell",
            position_side=position.side,
            ts=position.exit_ts or position.entry_ts,
            price=position.exit_price or position.entry_price,
            notional_usd=position.notional_usd,
            fee_usd=0.0,
            reason=reason,
            attrs={},
        )

    def positions(self) -> list[Position]:
        return list(self._positions)
