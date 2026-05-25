from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from cryptov2.data.okx_candles import Candle
from cryptov2.data.schemas import BarSize, fmt_ts

BAR_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1H": 3_600_000}


@dataclass(frozen=True, slots=True)
class CandleQuality:
    inst_id: str
    bar: str
    rows: int
    start: str | None
    end: str | None
    gaps: int
    duplicates: int
    unconfirmed: int


def inspect_candles(inst_id: str, bar: str, candles: list[Candle]) -> CandleQuality:
    if not candles:
        return CandleQuality(inst_id, bar, 0, None, None, 0, 0, 0)
    step = BAR_MS[bar]
    seen = set()
    duplicates = 0
    gaps = 0
    prev = None
    unconfirmed = 0
    for candle in sorted(candles, key=lambda item: item.ts):
        if candle.confirm != 1:
            unconfirmed += 1
        if candle.ts in seen:
            duplicates += 1
        seen.add(candle.ts)
        if prev is not None and candle.ts - prev != step:
            gaps += 1
        prev = candle.ts
    ordered = sorted(candles, key=lambda item: item.ts)
    return CandleQuality(
        inst_id=inst_id,
        bar=bar,
        rows=len(candles),
        start=fmt_ts(ordered[0].ts),
        end=fmt_ts(ordered[-1].ts),
        gaps=gaps,
        duplicates=duplicates,
        unconfirmed=unconfirmed,
    )


def write_catalog(path: Path | str, reports: list[CandleQuality], extra: dict | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "symbols": len(reports),
            "rows_total": sum(item.rows for item in reports),
            "symbols_with_gaps": sum(1 for item in reports if item.gaps > 0),
            "symbols_with_duplicates": sum(1 for item in reports if item.duplicates > 0),
            "symbols_with_unconfirmed": sum(1 for item in reports if item.unconfirmed > 0),
        },
        "extra": extra or {},
        "details": [asdict(item) for item in reports],
    }
    with path.open("w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
