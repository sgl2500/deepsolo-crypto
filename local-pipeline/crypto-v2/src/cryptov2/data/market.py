from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cryptov2.data.okx_candles import Candle, parse_okx_candles


class MarketDataClient(Protocol):
    def get_instruments(self, inst_type: str = "SWAP") -> list[dict]: ...
    def get_tickers(self, inst_type: str = "SWAP") -> list[dict]: ...
    def get_candles(self, inst_id: str, bar: str = "1m", limit: int = 300) -> list[list[str]]: ...
    def get_history_candles(self, inst_id: str, bar: str = "1m", limit: int = 300, after: str | None = None, before: str | None = None) -> list[list[str]]: ...


@dataclass(frozen=True, slots=True)
class Instrument:
    inst_id: str
    inst_type: str
    settle_ccy: str
    state: str
    ct_val: float
    lot_sz: float
    min_sz: float

    @classmethod
    def from_okx(cls, data: dict) -> "Instrument":
        def f(value, default=0.0):
            try:
                return float(value) if value not in (None, "") else default
            except (TypeError, ValueError):
                return default
        return cls(
            inst_id=data.get("instId", ""),
            inst_type=data.get("instType", ""),
            settle_ccy=data.get("settleCcy", ""),
            state=data.get("state", ""),
            ct_val=f(data.get("ctVal")),
            lot_sz=f(data.get("lotSz")),
            min_sz=f(data.get("minSz")),
        )


@dataclass(frozen=True, slots=True)
class Ticker:
    inst_id: str
    last: float
    bid_px: float
    ask_px: float
    open24h: float
    high24h: float
    low24h: float
    vol_ccy_24h: float

    @property
    def vol_usdt_24h(self) -> float:
        return self.vol_ccy_24h * self.last

    @classmethod
    def from_okx(cls, data: dict) -> "Ticker":
        def f(value, default=0.0):
            try:
                return float(value) if value not in (None, "") else default
            except (TypeError, ValueError):
                return default
        return cls(
            inst_id=data.get("instId", ""),
            last=f(data.get("last")),
            bid_px=f(data.get("bidPx")),
            ask_px=f(data.get("askPx")),
            open24h=f(data.get("open24h")),
            high24h=f(data.get("high24h")),
            low24h=f(data.get("low24h")),
            vol_ccy_24h=f(data.get("volCcy24h")),
        )


class MarketDataService:
    def __init__(self, client: MarketDataClient):
        self.client = client

    def usdt_swap_instruments(self, live_only: bool = True) -> list[Instrument]:
        instruments = [Instrument.from_okx(item) for item in self.client.get_instruments("SWAP")]
        output = [item for item in instruments if item.settle_ccy == "USDT"]
        if live_only:
            output = [item for item in output if item.state in ("", "live")]
        return sorted(output, key=lambda item: item.inst_id)

    def tickers(self) -> dict[str, Ticker]:
        return {item.inst_id: item for item in (Ticker.from_okx(row) for row in self.client.get_tickers("SWAP"))}

    def recent_candles(self, inst_id: str, bar: str = "1m", limit: int = 300) -> list[Candle]:
        rows = self.client.get_candles(inst_id, bar=bar, limit=limit)
        return parse_okx_candles(inst_id, rows, source="recent")

    def history_candles(self, inst_id: str, bar: str = "1m", limit: int = 300, after: str | None = None) -> list[Candle]:
        rows = self.client.get_history_candles(inst_id, bar=bar, limit=limit, after=after)
        return parse_okx_candles(inst_id, rows, source="history")
