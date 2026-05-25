from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from cryptov2.data.okx_candles import Candle
from cryptov2.data.schemas import Bar, BarSize
from cryptov2.data.storage.candle_store import CANDLE_FIELDS


class GzipPartitionedCandleStore:
    """Compressed, date-partitioned CSV store using only the Python stdlib.

    Layout:
      <root>/candles_1m/date=YYYY-MM-DD/BTC-USDT-SWAP.csv.gz

    Partition dates are UTC dates derived from the candle timestamp. This is a
    practical fallback until DuckDB/Parquet dependencies are available.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def partition_date(self, ts_ms: int) -> str:
        return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")

    def path(self, bar: BarSize, inst_id: str, date: str) -> Path:
        return self.root / f"candles_{bar}" / f"date={date}" / f"{inst_id}.csv.gz"

    def symbols(self, bar: BarSize = "5m") -> list[str]:
        folder = self.root / f"candles_{bar}"
        if not folder.exists():
            return []
        return sorted({path.name.removesuffix(".csv.gz") for path in folder.glob("date=*/*.csv.gz")})

    def _read_file(self, path: Path, confirmed_only: bool = True) -> list[Candle]:
        if not path.exists():
            return []
        rows: list[Candle] = []
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    candle = Candle(
                        inst_id=row["inst_id"],
                        ts=int(row["ts"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        vol=float(row.get("vol") or 0),
                        vol_ccy=float(row.get("vol_ccy") or 0),
                        vol_ccy_quote=float(row.get("vol_ccy_quote") or 0),
                        confirm=int(row.get("confirm") or 1),
                        source=row.get("source") or "unknown",
                        ingested_at=int(row.get("ingested_at") or 0),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if confirmed_only and candle.confirm != 1:
                    continue
                rows.append(candle)
        return sorted(rows, key=lambda candle: candle.ts)

    def read_candles(self, bar: BarSize, inst_id: str, confirmed_only: bool = True) -> list[Candle]:
        folder = self.root / f"candles_{bar}"
        if not folder.exists():
            return []
        rows: list[Candle] = []
        for path in sorted(folder.glob(f"date=*/{inst_id}.csv.gz")):
            rows.extend(self._read_file(path, confirmed_only=confirmed_only))
        return sorted(rows, key=lambda candle: candle.ts)

    def read_bars(self, bar: BarSize, inst_id: str) -> list[Bar]:
        return [candle.to_bar() for candle in self.read_candles(bar, inst_id, confirmed_only=True)]

    def upsert_candles(self, bar: BarSize, inst_id: str, candles: list[Candle]) -> int:
        grouped: dict[str, list[Candle]] = defaultdict(list)
        for candle in candles:
            if candle.inst_id != inst_id:
                raise ValueError(f"candle inst_id mismatch: {candle.inst_id} != {inst_id}")
            grouped[self.partition_date(candle.ts)].append(candle)

        for date, incoming in grouped.items():
            path = self.path(bar, inst_id, date)
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = {candle.ts: candle for candle in self._read_file(path, confirmed_only=False)}
            for candle in incoming:
                existing[candle.ts] = candle
            ordered = [existing[ts] for ts in sorted(existing)]
            tmp = path.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CANDLE_FIELDS)
                writer.writeheader()
                for candle in ordered:
                    writer.writerow(asdict(candle))
            tmp.replace(path)
        return len(candles)
