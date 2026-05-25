#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cryptov2.data.aggregation import aggregate_candles
from cryptov2.data.instruments_dim import select_instrument_symbols
from cryptov2.data.symbols import read_symbol_catalog
from cryptov2.data.storage.factory import create_candle_store


def resolve_symbols(args, store) -> list[str]:
    if args.symbols:
        symbols = sorted(args.symbols)
    elif args.dim_catalog.exists():
        symbols = select_instrument_symbols(args.dim_catalog, online_only=True, backfill_enabled_only=True)
    elif args.symbol_catalog.exists():
        symbols = read_symbol_catalog(args.symbol_catalog)
    else:
        symbols = store.symbols("1m")
    return symbols[: args.symbol_limit] if args.symbol_limit else symbols


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild 5m/15m/1H aggregates from normalized 1m candles.")
    parser.add_argument("--store-backend", choices=["gzip_partition"], default="gzip_partition")
    parser.add_argument("--normalized-root", type=Path, default=ROOT / "data" / "normalized_gzip")
    parser.add_argument("--dim-catalog", type=Path, default=ROOT / "data" / "catalog" / "instruments_okx_usdt_swap_dim.json")
    parser.add_argument("--symbol-catalog", type=Path, default=ROOT / "data" / "catalog" / "symbols_usdt_swap.json")
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbol-limit", type=int, default=None)
    args = parser.parse_args()

    store = create_candle_store(args.store_backend, args.normalized_root)
    symbols = resolve_symbols(args, store)
    totals = {"5m": 0, "15m": 0, "1H": 0}

    for idx, inst_id in enumerate(symbols, 1):
        one_min = store.read_candles("1m", inst_id, confirmed_only=True)
        counts: dict[str, int] = {}
        for target in ("5m", "15m", "1H"):
            aggregated = aggregate_candles(one_min, target)
            written = store.upsert_candles(target, inst_id, aggregated)
            counts[target] = written
            totals[target] += written
        print(
            f"[{idx}/{len(symbols)}] {inst_id}: 1m={len(one_min)} "
            f"5m={counts['5m']} 15m={counts['15m']} 1H={counts['1H']}",
            flush=True,
        )

    print(
        "aggregate rebuild done: "
        f"symbols={len(symbols)} 5m={totals['5m']} 15m={totals['15m']} 1H={totals['1H']} "
        f"output={args.normalized_root}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
