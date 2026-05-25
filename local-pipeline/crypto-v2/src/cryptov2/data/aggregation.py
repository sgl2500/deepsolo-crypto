from __future__ import annotations

from dataclasses import replace

from cryptov2.data.okx_candles import Candle
from cryptov2.data.schemas import BarSize

BAR_MS = {"5m": 5 * 60_000, "15m": 15 * 60_000, "1H": 60 * 60_000}
SOURCE_PREFIX = "agg_1m_to_"


def aggregate_candles(candles_1m: list[Candle], target_bar: BarSize) -> list[Candle]:
    if target_bar not in BAR_MS:
        raise ValueError(f"unsupported aggregate target: {target_bar}")
    step = BAR_MS[target_bar]
    expected_count = step // 60_000
    grouped: dict[tuple[str, int], list[Candle]] = {}
    for candle in candles_1m:
        if candle.confirm != 1:
            continue
        bucket = (candle.ts // step) * step
        grouped.setdefault((candle.inst_id, bucket), []).append(candle)

    output: list[Candle] = []
    for (inst_id, bucket), rows in sorted(grouped.items(), key=lambda item: item[0]):
        rows.sort(key=lambda candle: candle.ts)
        expected_ts = list(range(bucket, bucket + step, 60_000))
        if [candle.ts for candle in rows] != expected_ts or len(rows) != expected_count:
            continue
        output.append(Candle(
            inst_id=inst_id,
            ts=bucket,
            open=rows[0].open,
            high=max(candle.high for candle in rows),
            low=min(candle.low for candle in rows),
            close=rows[-1].close,
            vol=sum(candle.vol for candle in rows),
            vol_ccy=sum(candle.vol_ccy for candle in rows),
            vol_ccy_quote=sum(candle.vol_ccy_quote for candle in rows),
            confirm=1,
            source=f"{SOURCE_PREFIX}{target_bar}",
            ingested_at=max(candle.ingested_at for candle in rows),
        ))
    return output
