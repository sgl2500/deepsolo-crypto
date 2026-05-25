#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cryptov2.data.aggregation import aggregate_candles
from cryptov2.data.catalog import inspect_candles, write_catalog
from cryptov2.data.instruments_dim import select_instrument_symbols, sync_instrument_dim
from cryptov2.data.okx_candles import parse_okx_candles
from cryptov2.data.okx_client import OkxRestClient, OkxRestClientConfig
from cryptov2.data.relay_client import RelayClient, RelayClientConfig
from cryptov2.data.market import MarketDataService
from cryptov2.data.state import DownloadState
from cryptov2.data.symbols import load_usdt_swap_symbols, read_symbol_catalog, write_symbol_catalog
from cryptov2.data.storage.candle_store import RawJsonlStore
from cryptov2.data.storage.factory import create_candle_store

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_attempts: int
    base_sleep_seconds: float
    max_sleep_seconds: float
    jitter_ratio: float


def is_retryable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_markers = [
        "429",
        "too many requests",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "http error 502",
        "http error 503",
        "http error 504",
    ]
    return any(marker in message for marker in retryable_markers)


def retry_sleep_seconds(attempt: int, config: RetryConfig) -> float:
    sleep_seconds = min(config.max_sleep_seconds, config.base_sleep_seconds * (2 ** (attempt - 1)))
    if config.jitter_ratio <= 0:
        return sleep_seconds
    jitter = sleep_seconds * config.jitter_ratio
    return max(0.0, sleep_seconds + random.uniform(-jitter, jitter))


def call_with_retry(label: str, fn: Callable[[], T], config: RetryConfig) -> T:
    for attempt in range(1, config.max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= config.max_attempts or not is_retryable_error(exc):
                raise
            sleep_seconds = retry_sleep_seconds(attempt, config)
            print(
                f"{label}: transient error attempt {attempt}/{config.max_attempts}: "
                f"{exc}; sleep {sleep_seconds:.1f}s",
                flush=True,
            )
            time.sleep(sleep_seconds)
    raise RuntimeError(f"unreachable retry state: {label}")


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


def select_symbols(args, service: MarketDataService) -> list[str]:
    if args.symbols:
        return sorted(args.symbols)
    if args.dim_catalog.exists():
        symbols = select_instrument_symbols(
            args.dim_catalog,
            online_only=not args.include_offline,
            backfill_enabled_only=True,
        )
        if symbols:
            return symbols[: args.symbol_limit] if args.symbol_limit else symbols
    if args.symbol_catalog.exists():
        symbols = read_symbol_catalog(args.symbol_catalog)
        if symbols:
            return symbols[: args.symbol_limit] if args.symbol_limit else symbols
    instruments = load_usdt_swap_symbols(service, live_only=True)
    write_symbol_catalog(args.symbol_catalog, instruments, {"source": "backfill"})
    symbols = [item.inst_id for item in instruments]
    return symbols[: args.symbol_limit] if args.symbol_limit else symbols


def fetch_history_pages(
    client: OkxRestClient,
    inst_id: str,
    bar: str,
    pages: int,
    sleep_seconds: float,
    retry_config: RetryConfig,
) -> list[list[str]]:
    rows: list[list[str]] = []
    seen = set()
    after = None
    for page in range(pages):
        batch = call_with_retry(
            f"{inst_id} history page {page + 1}/{pages}",
            lambda: client.get_history_candles(inst_id, bar=bar, limit=300, after=after),
            retry_config,
        )
        if not batch:
            break
        for row in batch:
            if row[0] not in seen:
                seen.add(row[0])
                rows.append(row)
        after = batch[-1][0]
        time.sleep(sleep_seconds)
    rows.sort(key=lambda row: int(row[0]))
    return rows


def fetch_recent(client: OkxRestClient, inst_id: str, bar: str, retry_config: RetryConfig) -> list[list[str]]:
    rows = call_with_retry(
        f"{inst_id} recent candles",
        lambda: client.get_candles(inst_id, bar=bar, limit=300),
        retry_config,
    )
    return sorted(rows, key=lambda row: int(row[0]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill OKX 1m candles into raw + normalized stores.")
    parser.add_argument("--source", choices=["relay", "okx"], default="okx")
    parser.add_argument("--base-url", default=None, help="Defaults to OKX official for --source okx. Relay source requires this or OKX_RELAY_BASE_URL.")
    parser.add_argument("--bar", default="1m", choices=["1m"])
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbol-limit", type=int, default=None)
    parser.add_argument("--pages", type=int, default=2, help="History pages per symbol; 2 pages ~= 600 minutes.")
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retry-attempts", type=int, default=8)
    parser.add_argument("--retry-base-sleep", type=float, default=60.0)
    parser.add_argument("--retry-max-sleep", type=float, default=180.0)
    parser.add_argument("--retry-jitter", type=float, default=0.15)
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    parser.add_argument("--store-backend", choices=["csv", "gzip_partition"], default="gzip_partition")
    parser.add_argument("--normalized-root", type=Path, default=None)
    parser.add_argument("--raw-root", type=Path, default=ROOT / "data" / "raw" / "okx")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog" / "okx_1m_quality.json")
    parser.add_argument("--symbol-catalog", type=Path, default=ROOT / "data" / "catalog" / "symbols_usdt_swap.json")
    parser.add_argument("--dim-catalog", type=Path, default=ROOT / "data" / "catalog" / "instruments_okx_usdt_swap_dim.json")
    parser.add_argument("--snapshot-dir", type=Path, default=ROOT / "data" / "catalog" / "instrument_snapshots" / "okx_swap")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "catalog" / "download_state.json")
    parser.add_argument("--resume", action="store_true", help="Skip symbols that already completed at least this many pages.")
    parser.add_argument("--include-offline", action="store_true", help="Backfill all known dimension rows, including offline instruments.")
    parser.add_argument("--no-sync-instruments", action="store_true", help="Skip pre-run OKX instrument dimension sync.")
    parser.add_argument("--no-aggregate", action="store_true")
    args = parser.parse_args()
    if args.normalized_root is None:
        folder = "normalized_gzip" if args.store_backend == "gzip_partition" else "normalized"
        args.normalized_root = ROOT / "data" / folder
    retry_config = RetryConfig(
        max_attempts=args.retry_attempts,
        base_sleep_seconds=args.retry_base_sleep,
        max_sleep_seconds=args.retry_max_sleep,
        jitter_ratio=args.retry_jitter,
    )

    if args.source == "relay":
        client = RelayClient(RelayClientConfig.from_env(args.base_url, timeout_seconds=args.timeout))
    else:
        client = OkxRestClient(OkxRestClientConfig(base_url=args.base_url or "https://www.okx.com", timeout_seconds=args.timeout))
    service = MarketDataService(client)
    sync_symbols_if_needed(args, client)
    store = create_candle_store(args.store_backend, args.normalized_root)
    raw_store = RawJsonlStore(args.raw_root)
    state = DownloadState(args.state)
    symbols = select_symbols(args, service)
    reports = []
    errors = []

    for idx, inst_id in enumerate(symbols, 1):
        try:
            current_state = state.get_symbol(inst_id)
            if args.resume and current_state.get("backfill_status") == "ok" and int(current_state.get("backfill_pages", 0)) >= args.pages:
                print(f"[{idx}/{len(symbols)}] {inst_id}: SKIP resume complete")
                continue
            history_rows = fetch_history_pages(client, inst_id, args.bar, args.pages, args.sleep, retry_config)
            recent_rows = fetch_recent(client, inst_id, args.bar, retry_config)
            raw_rows = history_rows + recent_rows
            raw_store.append(
                "candles_1m",
                inst_id,
                raw_rows,
                {"inst_id": inst_id, "bar": args.bar, "source": args.source, "pages": args.pages},
            )
            candles = parse_okx_candles(inst_id, raw_rows, source=args.source)
            confirmed = [candle for candle in candles if candle.confirm == 1]
            store.upsert_candles("1m", inst_id, confirmed)

            one_min = store.read_candles("1m", inst_id, confirmed_only=True)
            if not args.no_aggregate:
                for target in ["5m", "15m", "1H"]:
                    aggregated = aggregate_candles(one_min, target)
                    store.upsert_candles(target, inst_id, aggregated)
            report = inspect_candles(inst_id, "1m", one_min)
            reports.append(report)
            state.update_symbol(inst_id, {"backfill_status": "ok", "backfill_pages": args.pages, "backfill_rows": len(one_min), "backfill_end": report.end, "source": args.source})
            print(f"[{idx}/{len(symbols)}] {inst_id}: 1m rows={len(one_min)} new_confirmed={len(confirmed)}", flush=True)
        except Exception as exc:
            errors.append({"inst_id": inst_id, "error": str(exc)})
            state.update_symbol(inst_id, {"backfill_status": "error", "backfill_error": str(exc), "source": args.source})
            print(f"[{idx}/{len(symbols)}] {inst_id}: ERROR {exc}", flush=True)
            if not args.continue_on_error:
                raise

    write_catalog(args.catalog, reports, {
        "symbols": symbols,
        "bar": args.bar,
        "pages": args.pages,
        "source": args.source,
        "store_backend": args.store_backend,
        "normalized_root": str(args.normalized_root),
        "retry_attempts": args.retry_attempts,
        "retry_base_sleep": args.retry_base_sleep,
        "retry_max_sleep": args.retry_max_sleep,
        "errors": errors,
    })
    print(f"Saved catalog: {args.catalog}")


if __name__ == "__main__":
    main()
