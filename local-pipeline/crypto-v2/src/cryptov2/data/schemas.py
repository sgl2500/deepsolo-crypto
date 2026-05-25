from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Literal

CST = timezone(timedelta(hours=8))
HOUR_MS = 60 * 60 * 1000
MIN5_MS = 5 * 60 * 1000

BarSize = Literal["1m", "5m", "15m", "1H", "1D"]
Side = Literal["buy", "sell"]
PositionSide = Literal["long", "short"]


class StopModel(str, Enum):
    HARD_INTRABAR = "hard_stop_intrabar"
    BOT_CHECKPOINT = "bot_like_checkpoint"


@dataclass(frozen=True, slots=True)
class Bar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    vol: float = 0.0
    vol_ccy: float = 0.0

    @property
    def change_pct(self) -> float:
        if self.open <= 0:
            return 0.0
        return (self.close - self.open) / self.open * 100.0

    @property
    def is_green(self) -> bool:
        return self.close > self.open

    def time_str(self) -> str:
        return datetime.fromtimestamp(self.ts / 1000, CST).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True, slots=True)
class Signal:
    strategy: str
    inst_id: str
    signal_ts: int
    confirm_ts: int
    strength: float
    attrs: dict


@dataclass(frozen=True, slots=True)
class OrderIntent:
    strategy: str
    inst_id: str
    side: Side
    position_side: PositionSide
    ts: int
    ref_price: float
    notional_usd: float
    reason: str
    attrs: dict


@dataclass(slots=True)
class Fill:
    strategy: str
    inst_id: str
    side: Side
    position_side: PositionSide
    ts: int
    price: float
    notional_usd: float
    fee_usd: float
    reason: str
    attrs: dict


@dataclass(slots=True)
class Position:
    strategy: str
    inst_id: str
    side: PositionSide
    entry_ts: int
    entry_price: float
    notional_usd: float
    attrs: dict
    exit_ts: int | None = None
    exit_price: float | None = None
    gross_pnl_pct: float | None = None
    net_pnl_pct: float | None = None
    reason: str | None = None
    max_adverse_pct: float = 0.0
    max_favorable_pct: float = 0.0


def fmt_ts(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, CST).strftime("%Y-%m-%d %H:%M")


def short_pnl_pct(exit_price: float, entry_price: float) -> float:
    return -(exit_price - entry_price) / entry_price * 100.0
