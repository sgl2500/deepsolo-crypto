from __future__ import annotations

import csv
import gzip
import json
from dataclasses import asdict
from pathlib import Path

from cryptov2.data.okx_candles import Candle
from cryptov2.data.schemas import Bar, BarSize

CANDLE_FIELDS = [
    "inst_id",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "vol_ccy",
    "vol_ccy_quote",
    "confirm",
    "source",
    "ingested_at",
]


class CandleStore:
    """CSV normalized candle store with timestamp upsert semantics."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path(self, bar: BarSize, inst_id: str) -> Path:
        return self.root / f"candles_{bar}" / f"{inst_id}.csv"

    def symbols(self, bar: BarSize = "5m") -> list[str]:
        folder = self.root / f"candles_{bar}"
        if not folder.exists():
            return []
        return sorted(path.stem for path in folder.glob("*.csv"))

    def read_candles(self, bar: BarSize, inst_id: str, confirmed_only: bool = True) -> list[Candle]:
        path = self.path(bar, inst_id)
        if not path.exists():
            return []
        rows: list[Candle] = []
        with path.open() as f:
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

    def read_bars(self, bar: BarSize, inst_id: str) -> list[Bar]:
        return [candle.to_bar() for candle in self.read_candles(bar, inst_id, confirmed_only=True)]

    def upsert_candles(self, bar: BarSize, inst_id: str, candles: list[Candle]) -> int:
        path = self.path(bar, inst_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = {candle.ts: candle for candle in self.read_candles(bar, inst_id, confirmed_only=False)}
        for candle in candles:
            if candle.inst_id != inst_id:
                raise ValueError(f"candle inst_id mismatch: {candle.inst_id} != {inst_id}")
            existing[candle.ts] = candle
        ordered = [existing[ts] for ts in sorted(existing)]
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CANDLE_FIELDS)
            writer.writeheader()
            for candle in ordered:
                writer.writerow(asdict(candle))
        tmp.replace(path)
        return len(candles)


class RawJsonlStore:
    """Append raw OKX payloads into gzip JSONL partitions."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def append(self, category: str, inst_id: str, rows: list, meta: dict) -> Path:
        path = self.root / category / f"{inst_id}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "at", encoding="utf-8") as f:
            f.write(json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False) + "\n")
        return path
