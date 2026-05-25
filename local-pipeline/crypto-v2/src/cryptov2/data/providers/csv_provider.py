from __future__ import annotations

import csv
from pathlib import Path

from cryptov2.data.schemas import Bar, BarSize, HOUR_MS, MIN5_MS


class CsvKlineProvider:
    """Read local OHLCV CSVs laid out as <root>/<bar>/<inst_id>.csv."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def symbols(self, bar: BarSize = "5m") -> list[str]:
        folder = self.root / bar
        if not folder.exists():
            return []
        return sorted(path.stem for path in folder.glob("*.csv"))

    def load_bars(self, inst_id: str, bar: BarSize) -> list[Bar]:
        path = self.root / bar / f"{inst_id}.csv"
        if not path.exists():
            return []
        bars: list[Bar] = []
        with path.open() as f:
            for row in csv.DictReader(f):
                try:
                    bars.append(Bar(
                        ts=int(row["ts"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        vol=float(row.get("vol") or 0),
                        vol_ccy=float(row.get("vol_ccy") or 0),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
        return sorted(bars, key=lambda bar_: bar_.ts)

    def load_1h_from_5m(self, inst_id: str) -> list[Bar]:
        return aggregate_1h_from_5m(self.load_bars(inst_id, "5m"))


def aggregate_1h_from_5m(bars_5m: list[Bar]) -> list[Bar]:
    grouped: dict[int, list[Bar]] = {}
    for bar in bars_5m:
        hour_ts = (bar.ts // HOUR_MS) * HOUR_MS
        grouped.setdefault(hour_ts, []).append(bar)

    hourly: list[Bar] = []
    for hour_ts, bars in sorted(grouped.items()):
        bars.sort(key=lambda bar: bar.ts)
        expected = list(range(hour_ts, hour_ts + HOUR_MS, MIN5_MS))
        if [bar.ts for bar in bars] != expected:
            continue
        hourly.append(Bar(
            ts=hour_ts,
            open=bars[0].open,
            high=max(bar.high for bar in bars),
            low=min(bar.low for bar in bars),
            close=bars[-1].close,
            vol=sum(bar.vol for bar in bars),
            vol_ccy=sum(bar.vol_ccy for bar in bars),
        ))
    return hourly
