from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from cryptov2.data.schemas import Bar, OrderIntent, Signal


@dataclass(slots=True)
class StrategyContext:
    now_ts: int
    capital_per_trade_usd: float
    open_positions: dict[str, object]


class Strategy(ABC):
    name: str

    @abstractmethod
    def prepare_symbol(self, inst_id: str, bars_1h: list[Bar], bars_5m: list[Bar]) -> list[Signal]:
        """Precompute historical signals for a symbol."""

    @abstractmethod
    def order_for_signal(
        self,
        signal: Signal,
        bars_5m: list[Bar],
        context: StrategyContext,
    ) -> OrderIntent | None:
        """Return an entry order intent for a signal if entry conditions are met."""
