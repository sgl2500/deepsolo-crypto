#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cryptov2.data.aggregation import aggregate_candles
from cryptov2.data.catalog import inspect_candles, write_catalog
from cryptov2.data.instruments_dim import select_instrument_symbols, sync_instrument_dim
from cryptov2.data.market import MarketDataService
from cryptov2.data.okx_candles import parse_okx_candles
from cryptov2.data.okx_client import OkxRestClient, OkxRestClientConfig
from cryptov2.data.relay_client import RelayClient, RelayClientConfig
from cryptov2.data.state import DownloadState
from cryptov2.data.storage.candle_store import RawJsonlStore
from cryptov2.data.storage.factory import CandleStoreProtocol, create_candle_store
from cryptov2.data.symbols import load_usdt_swap_symbols, read_symbol_catalog, write_symbol_catalog


def build_client(args):
    if args.source == "relay":
        return RelayClient(RelayClientConfig.from_env(args.base_url, timeout_seconds=args.timeout))
    return OkxRestClient(OkxRestClientConfig(base_url=args.base_url or "https://www.okx.com", timeout_seconds=args.timeout))


def sync_symbols_if_needed(args, client) -> None:
    if args.no_sync_instruments:
        return
    raw_rows = client.get_instruments("SWAP")
    _payload, stats = sync_instrument_dim(
        raw_rows=raw_rows,
        dim_path=args.dim_catalog,
        snapshot_dir=args.snapshot_dir,
        legacy_symbol_catalog=args.symbol_catalog,
        source=args.source,
    )
    print(
        "instrument dim synced: "
        f"new={stats['new']} online={stats['online']} offline={stats['offline']} "
        f"changed_state={stats['changed_state']} missing={stats['missing']}"
    )


def resolve_symbols(args, service: MarketDataService) -> list[str]:
    if args.symbols:
        return sorted(args.symbols)
    if args.dim_catalog.exists():
        symbols = select_instrument_symbols(args.dim_catalog, online_only=True)
        if symbols:
            return symbols[: args.symbol_limit] if args.symbol_limit else symbols
    if args.symbol_catalog.exists():
        symbols = read_symbol_catalog(args.symbol_catalog)
        if symbols:
            return symbols[: args.symbol_limit] if args.symbol_limit else symbols
    instruments = load_usdt_swap_symbols(service, live_only=True)
    write_symbol_catalog(args.symbol_catalog, instruments, {"source": args.source})
    symbols = [item.inst_id for item in instruments]
    return symbols[: args.symbol_limit] if args.symbol_limit else symbols


def update_symbol(args, client, store: CandleStoreProtocol, raw_store: RawJsonlStore, inst_id: str):
    rows = client.get_candles(inst_id, bar="1m", limit=args.limit)
    raw_store.append("candles_1m_recent", inst_id, rows, {"source": args.source, "limit": args.limit})
    candles = parse_okx_candles(inst_id, rows, source=f"{args.source}_recent")
    confirmed = [candle for candle in candles if candle.confirm == 1]
    store.upsert_candles("1m", inst_id, confirmed)
    one_min = store.read_candles("1m", inst_id, confirmed_only=True)
    if not args.no_aggregate:
        for target in ["5m", "15m", "1H"]:
            store.upsert_candles(target, inst_id, aggregate_candles(one_min, target))
    return one_min, len(confirmed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh recent OKX USDT SWAP 1m candles and rebuild aggregates.")
    parser.add_argument("--source", choices=["relay", "okx"], default="okx")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbol-limit", type=int, default=None)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--store-backend", choices=["csv", "gzip_partition"], default="gzip_partition")
    parser.add_argument("--normalized-root", type=Path, default=None)
    parser.add_argument("--raw-root", type=Path, default=ROOT / "data" / "raw" / "okx")
    parser.add_argument("--symbol-catalog", type=Path, default=ROOT / "data" / "catalog" / "symbols_usdt_swap.json")
    parser.add_argument("--dim-catalog", type=Path, default=ROOT / "data" / "catalog" / "instruments_okx_usdt_swap_dim.json")
    parser.add_argument("--snapshot-dir", type=Path, default=ROOT / "data" / "catalog" / "instrument_snapshots" / "okx_swap")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog" / "okx_1m_update_quality.json")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "catalog" / "download_state.json")
    parser.add_argument("--no-sync-instruments", action="store_true", help="Skip pre-run OKX instrument dimension sync.")
    parser.add_argument("--no-aggregate", action="store_true")
    args = parser.parse_args()
    if args.normalized_root is None:
        folder = "normalized_gzip" if args.store_backend == "gzip_partition" else "normalized"
        args.normalized_root = ROOT / "data" / folder

    client = build_client(args)
    service = MarketDataService(client)
    sync_symbols_if_needed(args, client)
    store = create_candle_store(args.store_backend, args.normalized_root)
    raw_store = RawJsonlStore(args.raw_root)
    state = DownloadState(args.state)
    symbols = resolve_symbols(args, service)
    reports = []
    errors = []

    for idx, inst_id in enumerate(symbols, 1):
        try:
            one_min, new_confirmed = update_symbol(args, client, store, raw_store, inst_id)
            report = inspect_candles(inst_id, "1m", one_min)
            reports.append(report)
            state.update_symbol(inst_id, {
                "last_update_status": "ok",
                "last_update_rows": len(one_min),
                "last_update_confirmed": new_confirmed,
                "last_update_end": report.end,
                "source": args.source,
            })
            print(f"[{idx}/{len(symbols)}] {inst_id}: rows={len(one_min)} refreshed={new_confirmed}")
        except Exception as exc:
            errors.append({"inst_id": inst_id, "error": str(exc)})
            state.update_symbol(inst_id, {"last_update_status": "error", "last_update_error": str(exc), "source": args.source})
            print(f"[{idx}/{len(symbols)}] {inst_id}: ERROR {exc}")
        time.sleep(args.sleep)

    write_catalog(args.catalog, reports, {
        "source": args.source,
        "symbols": symbols,
        "errors": errors,
        "mode": "recent_update",
        "store_backend": args.store_backend,
        "normalized_root": str(args.normalized_root),
    })
    print(f"Saved catalog: {args.catalog}")


if __name__ == "__main__":
    main()
