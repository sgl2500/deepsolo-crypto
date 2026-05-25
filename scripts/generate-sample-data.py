#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import math
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "sample_data" / "normalized_gzip"
FIELDS = [
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
CONTRACTS = [
    ("BTC-USDT-SWAP", 42000.0, 0.0007),
    ("ETH-USDT-SWAP", 2300.0, 0.0010),
    ("SOL-USDT-SWAP", 105.0, 0.0015),
]
TIMEFRAMES = {
    "candles_1m": (timedelta(minutes=1), 180),
    "candles_5m": (timedelta(minutes=5), 96),
    "candles_15m": (timedelta(minutes=15), 96),
    "candles_1H": (timedelta(hours=1), 72),
    "candles_1D": (timedelta(days=1), 12),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic sample normalized_gzip data.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output normalized_gzip root.")
    parser.add_argument("--start-date", default="2026-01-01", help="First date partition to generate.")
    parser.add_argument("--days", type=int, default=2, help="Number of date partitions to generate.")
    parser.add_argument("--force", action="store_true", help="Delete the output directory before generating.")
    args = parser.parse_args()

    output = args.output.expanduser()
    if not output.is_absolute():
        output = ROOT / output

    if output.exists() and args.force:
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    start = datetime.fromisoformat(args.start_date).replace(tzinfo=UTC)
    days = max(1, args.days)

    for directory, (step, rows_per_partition) in TIMEFRAMES.items():
        for day_index in range(days):
            partition_start = start + timedelta(days=day_index)
            partition_dir = output / directory / f"date={partition_start.date().isoformat()}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            for contract_index, (inst_id, base_price, drift) in enumerate(CONTRACTS):
                path = partition_dir / f"{inst_id}.csv.gz"
                rows = _rows(
                    inst_id=inst_id,
                    base_price=base_price,
                    drift=drift,
                    contract_index=contract_index,
                    start=partition_start,
                    step=step,
                    count=rows_per_partition,
                    day_index=day_index,
                )
                _write_csv_gz(path, rows)

    print(f"Sample data written to: {output}")
    print("Start with:")
    print(f"DATA_ROOT={output} ./scripts/start-local.sh")
    return 0


def _rows(
    *,
    inst_id: str,
    base_price: float,
    drift: float,
    contract_index: int,
    start: datetime,
    step: timedelta,
    count: int,
    day_index: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    previous_close = base_price * (1 + day_index * 0.015)
    for index in range(count):
        ts_dt = start + step * index
        wave = math.sin(index / 8 + contract_index) * 0.0025
        pulse = 0.009 if index in {45, 46, 47, 100} and contract_index == 2 else 0.0
        close = max(0.0001, previous_close * (1 + drift + wave + pulse))
        open_price = previous_close
        high = max(open_price, close) * 1.0018
        low = min(open_price, close) * 0.9982
        vol = 100 + contract_index * 35 + (index % 17) * 3
        if pulse:
            vol *= 3.5
        vol_quote = vol * close
        ts = int(ts_dt.timestamp() * 1000)
        rows.append(
            {
                "inst_id": inst_id,
                "ts": str(ts),
                "open": _num(open_price),
                "high": _num(high),
                "low": _num(low),
                "close": _num(close),
                "vol": _num(vol),
                "vol_ccy": _num(vol),
                "vol_ccy_quote": _num(vol_quote),
                "confirm": "1",
                "source": "sample",
                "ingested_at": str(ts + 30_000),
            }
        )
        previous_close = close
    return rows


def _write_csv_gz(path: Path, rows: list[dict[str, str]]) -> None:
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _num(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    raise SystemExit(main())
