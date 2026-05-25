#!/usr/bin/env python3
"""Build CST daily candles from complete 1H candles.

Output layout matches normalized_gzip partitions, but uses CST trading dates:
  data/normalized_gzip/candles_1D/date=YYYY-MM-DD/<inst_id>.csv.gz

A daily candle is written only when all 24 hourly candles for that CST day are
present and confirmed.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cryptov2.data.okx_candles import Candle
from cryptov2.data.storage.candle_store import CANDLE_FIELDS
from cryptov2.data.storage.factory import create_candle_store

CST = timezone(timedelta(hours=8))
HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS
SOURCE = "agg_1H_to_1D_CST"


def cst_day_start_ts(ts_ms: int) -> int:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=CST)
    day_start = datetime.combine(dt.date(), dt_time(0, 0), tzinfo=CST)
    return int(day_start.timestamp() * 1000)


def cst_partition_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=CST).strftime("%Y-%m-%d")


def aggregate_1d_cst(candles_1h: list[Candle]) -> list[Candle]:
    grouped: dict[int, list[Candle]] = defaultdict(list)
    for candle in candles_1h:
        if candle.confirm != 1:
            continue
        grouped[cst_day_start_ts(candle.ts)].append(candle)

    output: list[Candle] = []
    ingested_at = int(time.time() * 1000)
    for day_ts, rows in sorted(grouped.items()):
        rows.sort(key=lambda candle: candle.ts)
        expected_ts = list(range(day_ts, day_ts + DAY_MS, HOUR_MS))
        if [candle.ts for candle in rows] != expected_ts or len(rows) != 24:
            continue
        inst_id = rows[0].inst_id
        output.append(Candle(
            inst_id=inst_id,
            ts=day_ts,
            open=rows[0].open,
            high=max(candle.high for candle in rows),
            low=min(candle.low for candle in rows),
            close=rows[-1].close,
            vol=sum(candle.vol for candle in rows),
            vol_ccy=sum(candle.vol_ccy for candle in rows),
            vol_ccy_quote=sum(candle.vol_ccy_quote for candle in rows),
            confirm=1,
            source=SOURCE,
            ingested_at=ingested_at,
        ))
    return output


def read_gzip_csv(path: Path) -> list[Candle]:
    if not path.exists():
        return []
    rows: list[Candle] = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append(Candle(
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
                ))
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def write_partitioned_cst_daily(root: Path, inst_id: str, candles: list[Candle]) -> int:
    grouped: dict[str, list[Candle]] = defaultdict(list)
    for candle in candles:
        if candle.inst_id != inst_id:
            raise ValueError(f"candle inst_id mismatch: {candle.inst_id} != {inst_id}")
        grouped[cst_partition_date(candle.ts)].append(candle)

    for date, incoming in grouped.items():
        path = root / "candles_1D" / f"date={date}" / f"{inst_id}.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = {candle.ts: candle for candle in read_gzip_csv(path)}
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


def delete_existing_symbol_daily(root: Path, inst_id: str) -> int:
    folder = root / "candles_1D"
    if not folder.exists():
        return 0
    count = 0
    for path in folder.glob(f"date=*/{inst_id}.csv.gz"):
        path.unlink()
        count += 1
    return count


def parse_date_filter(text: str | None, *, end: bool = False) -> int | None:
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        dt = datetime.strptime(text, "%Y%m%d").replace(tzinfo=CST)
    else:
        dt = datetime.fromisoformat(text).astimezone(CST)
    if end:
        dt = datetime.combine(dt.date(), dt_time(23, 59, 59), tzinfo=CST)
    return int(dt.timestamp() * 1000)


def in_range(candle: Candle, start_ts: int | None, end_ts: int | None) -> bool:
    # Filter by the CST daily candle start timestamp.
    return (start_ts is None or candle.ts >= start_ts) and (end_ts is None or candle.ts <= end_ts)


def resolve_symbols(args, store) -> list[str]:
    symbols = sorted(args.symbols) if args.symbols else store.symbols("1H")
    if args.symbol_limit:
        symbols = symbols[: args.symbol_limit]
    return symbols


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CST 1D candles from complete normalized 1H candles.")
    parser.add_argument("--store-backend", choices=["gzip_partition"], default="gzip_partition")
    parser.add_argument("--normalized-root", type=Path, default=ROOT / "data" / "normalized_gzip")
    parser.add_argument("--symbols", nargs="*", default=[], help="Only rebuild these symbols")
    parser.add_argument("--symbol-limit", type=int, default=None, help="Limit symbol count for preview")
    parser.add_argument("--start", type=str, default=None, help="CST start date, e.g. 20260101")
    parser.add_argument("--end", type=str, default=None, help="CST end date, e.g. 20260520")
    parser.add_argument("--replace", action="store_true", help="Delete existing 1D files for each processed symbol before writing")
    parser.add_argument("--dry-run", action="store_true", help="Only print counts; do not write files")
    args = parser.parse_args()

    store = create_candle_store(args.store_backend, args.normalized_root)
    symbols = resolve_symbols(args, store)
    start_ts = parse_date_filter(args.start)
    end_ts = parse_date_filter(args.end, end=True)

    total_written = 0
    total_daily = 0
    total_deleted = 0
    for idx, inst_id in enumerate(symbols, start=1):
        candles_1h = store.read_candles("1H", inst_id, confirmed_only=True)
        daily = [candle for candle in aggregate_1d_cst(candles_1h) if in_range(candle, start_ts, end_ts)]
        total_daily += len(daily)
        deleted = 0
        written = 0
        if daily and not args.dry_run:
            if args.replace:
                deleted = delete_existing_symbol_daily(args.normalized_root, inst_id)
            written = write_partitioned_cst_daily(args.normalized_root, inst_id, daily)
        total_deleted += deleted
        total_written += written
        print(
            f"[{idx}/{len(symbols)}] {inst_id}: 1H={len(candles_1h)} "
            f"daily_complete={len(daily)} written={written} deleted={deleted}"
        )

    print(
        "done: "
        f"symbols={len(symbols)} daily_complete={total_daily} "
        f"written={total_written} deleted={total_deleted} "
        f"output={args.normalized_root / 'candles_1D'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
