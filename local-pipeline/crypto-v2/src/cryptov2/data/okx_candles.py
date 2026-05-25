from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

from cryptov2.data.schemas import Bar


@dataclass(frozen=True, slots=True)
class Candle:
    inst_id: str
    ts: int
    open: float
    high: float
    low: float
    close: float
    vol: float
    vol_ccy: float
    vol_ccy_quote: float
    confirm: int
    source: str
    ingested_at: int

    def to_bar(self) -> Bar:
        return Bar(self.ts, self.open, self.high, self.low, self.close, self.vol, self.vol_ccy)


def parse_okx_candle(inst_id: str, raw: list[str], source: str, ingested_at: int | None = None) -> Candle:
    if len(raw) < 6:
        raise ValueError(f"invalid OKX candle payload: {raw}")
    # OKX V5 candle shape: ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm.
    return Candle(
        inst_id=inst_id,
        ts=int(raw[0]),
        open=float(raw[1]),
        high=float(raw[2]),
        low=float(raw[3]),
        close=float(raw[4]),
        vol=float(raw[5]),
        vol_ccy=float(raw[6]) if len(raw) > 6 and raw[6] != "" else 0.0,
        vol_ccy_quote=float(raw[7]) if len(raw) > 7 and raw[7] != "" else 0.0,
        confirm=int(raw[8]) if len(raw) > 8 and raw[8] != "" else 1,
        source=source,
        ingested_at=ingested_at if ingested_at is not None else int(time.time() * 1000),
    )


def parse_okx_candles(inst_id: str, rows: Iterable[list[str]], source: str) -> list[Candle]:
    ingested_at = int(time.time() * 1000)
    candles = [parse_okx_candle(inst_id, row, source, ingested_at) for row in rows]
    return sorted(candles, key=lambda candle: candle.ts)
