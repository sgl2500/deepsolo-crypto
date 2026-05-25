#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cryptov2.data.instruments_dim import load_instrument_dim, select_instrument_rows, sync_instrument_dim
from cryptov2.data.market import MarketDataService
from cryptov2.data.okx_candles import parse_okx_candles
from cryptov2.data.okx_client import OkxRestClient, OkxRestClientConfig
from cryptov2.data.relay_client import RelayClient, RelayClientConfig
from cryptov2.data.storage.candle_store import RawJsonlStore
from cryptov2.data.storage.factory import create_candle_store
from cryptov2.data.symbols import load_usdt_swap_symbols, read_symbol_catalog, write_symbol_catalog

T = TypeVar("T")
CST = timezone(timedelta(hours=8))
UTC = timezone.utc
MINUTE_MS = 60_000
DAY_MS = 24 * 60 * MINUTE_MS


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_attempts: int
    base_sleep_seconds: float
    max_sleep_seconds: float
    jitter_ratio: float


@dataclass(frozen=True, slots=True)
class RepairDateReport:
    inst_id: str
    date: str
    expected_rows: int
    local_rows_before: int
    missing_before: int
    fetched_rows: int
    written_rows: int
    missing_after: int
    ignored_missing_after: int
    status: str
    error: str = ""


def parse_date(value: str) -> date:
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def date_start_ts_utc(value: date) -> int:
    return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)


def date_text(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def floor_minute(ts: int) -> int:
    return ts - (ts % MINUTE_MS)


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def is_retryable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "429",
            "too many requests",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "http error 502",
            "http error 503",
            "http error 504",
        )
    )


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
        f"changed_state={stats['changed_state']} missing={stats['missing']}",
        flush=True,
    )


def select_rows(args, service: MarketDataService) -> list[dict[str, Any]]:
    payload = load_instrument_dim(args.dim_catalog)
    rows = select_instrument_rows(payload, online_only=True, backfill_enabled_only=True)
    row_by_id = {str(row.get("inst_id")): row for row in rows if row.get("inst_id")}
    if args.symbols:
        selected = []
        for symbol in sorted(args.symbols):
            selected.append(row_by_id.get(symbol, {"inst_id": symbol, "is_online": True, "backfill_enabled": True}))
        return selected[: args.symbol_limit] if args.symbol_limit else selected
    if rows:
        return rows[: args.symbol_limit] if args.symbol_limit else rows
    if args.symbol_catalog.exists():
        symbols = read_symbol_catalog(args.symbol_catalog)
        fallback_rows = [{"inst_id": symbol, "is_online": True, "backfill_enabled": True} for symbol in symbols]
        return fallback_rows[: args.symbol_limit] if args.symbol_limit else fallback_rows
    instruments = load_usdt_swap_symbols(service, live_only=True)
    write_symbol_catalog(args.symbol_catalog, instruments, {"source": args.source})
    fallback_rows = [{"inst_id": item.inst_id, "is_online": True, "backfill_enabled": True} for item in instruments]
    return fallback_rows[: args.symbol_limit] if args.symbol_limit else fallback_rows


def earliest_partition_date(normalized_root: Path) -> date | None:
    folder = normalized_root / "candles_1m"
    if not folder.exists():
        return None
    dates: list[date] = []
    for path in folder.glob("date=*"):
        if not path.is_dir():
            continue
        try:
            dates.append(parse_date(path.name.replace("date=", "")))
        except ValueError:
            continue
    return min(dates) if dates else None


def local_confirmed_timestamps(normalized_root: Path, inst_id: str, item_date: date) -> set[int]:
    path = normalized_root / "candles_1m" / f"date={date_text(item_date)}" / f"{inst_id}.csv.gz"
    if not path.exists():
        return set()
    timestamps: set[int] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                ts = int(row["ts"])
            except (KeyError, TypeError, ValueError):
                continue
            if str(row.get("confirm", "1")) != "1":
                continue
            timestamps.add(ts)
    return timestamps


def effective_start_time(row: dict[str, Any]) -> int | None:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    values = [
        to_int(row.get("list_time") or raw.get("listTime")),
        to_int(raw.get("contTdSwTime")),
    ]
    starts = [value for value in values if value is not None]
    return max(starts) if starts else None


def expected_timestamps(row: dict[str, Any], item_date: date) -> set[int]:
    day_start = date_start_ts_utc(item_date)
    day_end = day_start + DAY_MS - MINUTE_MS
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    exp_time = to_int(row.get("exp_time") or raw.get("expTime"))
    start_time = effective_start_time(row)
    if start_time is not None and start_time > day_end:
        return set()
    if exp_time is not None and exp_time < day_start:
        return set()

    start_ts = day_start
    end_ts = day_end
    if start_time is not None and start_time > day_start:
        start_ts = floor_minute(start_time)
    if exp_time is not None and exp_time < day_end:
        end_ts = floor_minute(exp_time)
    if start_ts > end_ts:
        return set()
    return set(range(start_ts, end_ts + MINUTE_MS, MINUTE_MS))


def is_listing_edge_gap(row: dict[str, Any], item_date: date, expected: set[int], actual: set[int]) -> bool:
    if not expected or not actual:
        return False
    start_time = effective_start_time(row)
    if start_time is None:
        return False

    day_start = date_start_ts_utc(item_date)
    day_end = day_start + DAY_MS - MINUTE_MS
    if not (day_start <= start_time <= day_end):
        return False

    scoped_actual = actual & expected
    if not scoped_actual:
        return False
    missing = expected - scoped_actual
    first_expected = min(expected)
    first_actual = min(scoped_actual)
    if first_actual <= first_expected:
        return False
    return missing == set(range(first_expected, first_actual, MINUTE_MS))


def fetch_history_window(
    client,
    *,
    inst_id: str,
    start_ts: int,
    end_ts: int,
    sleep_seconds: float,
    retry_config: RetryConfig,
) -> list[list[str]]:
    rows_by_ts: dict[int, list[str]] = {}
    cursor = end_ts + MINUTE_MS
    max_pages = max(1, math.ceil((end_ts - start_ts + MINUTE_MS) / (300 * MINUTE_MS)) + 3)
    previous_oldest: int | None = None
    for page in range(1, max_pages + 1):
        batch = call_with_retry(
            f"{inst_id} repair history page {page}/{max_pages}",
            lambda cursor_value=cursor: client.get_history_candles(
                inst_id,
                bar="1m",
                limit=300,
                after=str(cursor_value),
            ),
            retry_config,
        )
        if not batch:
            break
        parsed_ts: list[int] = []
        for raw in batch:
            try:
                ts = int(raw[0])
            except (TypeError, ValueError, IndexError):
                continue
            parsed_ts.append(ts)
            if start_ts <= ts <= end_ts:
                rows_by_ts[ts] = raw
        if not parsed_ts:
            break
        oldest = min(parsed_ts)
        if oldest <= start_ts:
            break
        if previous_oldest is not None and oldest >= previous_oldest:
            break
        previous_oldest = oldest
        cursor = oldest
        time.sleep(sleep_seconds)
    return [rows_by_ts[ts] for ts in sorted(rows_by_ts)]


def repair_date(args, client, store, raw_store: RawJsonlStore, row: dict[str, Any], item_date: date, retry_config: RetryConfig) -> RepairDateReport:
    inst_id = str(row.get("inst_id"))
    expected = expected_timestamps(row, item_date)
    if not expected:
        return RepairDateReport(inst_id, date_text(item_date), 0, 0, 0, 0, 0, 0, 0, "skip")

    local_before = local_confirmed_timestamps(args.normalized_root, inst_id, item_date)
    missing = expected - local_before
    if not missing:
        return RepairDateReport(inst_id, date_text(item_date), len(expected), len(local_before), 0, 0, 0, 0, 0, "ok")

    fetched_total = 0
    written_total = 0
    error = ""
    missing_after = len(missing)
    for round_idx in range(1, args.repair_rounds + 1):
        try:
            raw_rows = fetch_history_window(
                client,
                inst_id=inst_id,
                start_ts=min(expected),
                end_ts=max(expected),
                sleep_seconds=args.sleep,
                retry_config=retry_config,
            )
            fetched_total += len(raw_rows)
            if raw_rows:
                raw_store.append(
                    "candles_1m_repair",
                    inst_id,
                    raw_rows,
                    {"inst_id": inst_id, "bar": "1m", "source": args.source, "date": date_text(item_date), "round": round_idx},
                )
                candles = [candle for candle in parse_okx_candles(inst_id, raw_rows, source=f"{args.source}_repair") if candle.confirm == 1]
                written_total += store.upsert_candles("1m", inst_id, candles)
        except Exception as exc:
            error = str(exc)
            break
        local_now = local_confirmed_timestamps(args.normalized_root, inst_id, item_date)
        missing_after = len(expected - local_now)
        if missing_after == 0:
            break

    local_after = local_confirmed_timestamps(args.normalized_root, inst_id, item_date)
    ignored_missing_after = 0
    status = "repaired"
    if missing_after > 0:
        if not error and is_listing_edge_gap(row, item_date, expected, local_after):
            ignored_missing_after = missing_after
            missing_after = 0
            status = "ignored_listing_edge"
        else:
            status = "failed"
    local_rows_before = len(local_before)
    return RepairDateReport(
        inst_id=inst_id,
        date=date_text(item_date),
        expected_rows=len(expected),
        local_rows_before=local_rows_before,
        missing_before=len(missing),
        fetched_rows=fetched_total,
        written_rows=written_total,
        missing_after=missing_after,
        ignored_missing_after=ignored_missing_after,
        status=status,
        error=error,
    )


def write_repair_report(path: Path, reports: list[RepairDateReport], extra: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "symbols": len(set(item.inst_id for item in reports)),
            "dates_checked": len(reports),
            "dates_repaired": sum(1 for item in reports if item.status == "repaired"),
            "dates_ignored": sum(1 for item in reports if item.status == "ignored_listing_edge"),
            "dates_failed": sum(1 for item in reports if item.status == "failed"),
            "missing_before": sum(item.missing_before for item in reports),
            "missing_after": sum(item.missing_after for item in reports),
            "ignored_missing_after": sum(item.ignored_missing_after for item in reports),
            "fetched_rows": sum(item.fetched_rows for item in reports),
            "written_rows": sum(item.written_rows for item in reports),
        },
        "extra": extra,
        "details": [asdict(item) for item in reports if item.status in {"repaired", "failed", "ignored_listing_edge"}],
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair complete-day 1m coverage by symbol/date.")
    parser.add_argument("--source", choices=["relay", "okx"], default="relay")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--symbol-limit", type=int, default=None)
    parser.add_argument("--start", type=str, default=None, help="UTC partition start date, e.g. 20260101")
    parser.add_argument("--end", type=str, default=None, help="UTC partition end date. Defaults to yesterday in CST.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--repair-rounds", type=int, default=2)
    parser.add_argument("--retry-attempts", type=int, default=5)
    parser.add_argument("--retry-base-sleep", type=float, default=3.0)
    parser.add_argument("--retry-max-sleep", type=float, default=30.0)
    parser.add_argument("--retry-jitter", type=float, default=0.15)
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any expected 1m candle remains missing.")
    parser.add_argument("--store-backend", choices=["gzip_partition"], default="gzip_partition")
    parser.add_argument("--normalized-root", type=Path, default=ROOT / "data" / "normalized_gzip")
    parser.add_argument("--raw-root", type=Path, default=ROOT / "data" / "raw" / "okx")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog" / "okx_1m_repair_quality.json")
    parser.add_argument("--symbol-catalog", type=Path, default=ROOT / "data" / "catalog" / "symbols_usdt_swap.json")
    parser.add_argument("--dim-catalog", type=Path, default=ROOT / "data" / "catalog" / "instruments_okx_usdt_swap_dim.json")
    parser.add_argument("--snapshot-dir", type=Path, default=ROOT / "data" / "catalog" / "instrument_snapshots" / "okx_swap")
    parser.add_argument("--no-sync-instruments", action="store_true")
    args = parser.parse_args()

    end_date = parse_date(args.end) if args.end else datetime.now(CST).date() - timedelta(days=1)
    local_start = earliest_partition_date(args.normalized_root)
    start_date = parse_date(args.start) if args.start else (local_start or end_date)
    if start_date > end_date:
        print(f"no complete date to repair: start={start_date} end={end_date}")
        write_repair_report(
            args.catalog,
            [],
            {"source": args.source, "start": date_text(start_date), "end": date_text(end_date), "reason": "empty_range"},
        )
        return 0

    retry_config = RetryConfig(
        max_attempts=args.retry_attempts,
        base_sleep_seconds=args.retry_base_sleep,
        max_sleep_seconds=args.retry_max_sleep,
        jitter_ratio=args.retry_jitter,
    )
    client = build_client(args)
    service = MarketDataService(client)
    sync_symbols_if_needed(args, client)
    rows = select_rows(args, service)
    store = create_candle_store(args.store_backend, args.normalized_root)
    raw_store = RawJsonlStore(args.raw_root)

    print(
        f"coverage repair range: start={start_date} end={end_date} "
        f"symbols={len(rows)} source={args.source}",
        flush=True,
    )
    reports: list[RepairDateReport] = []
    for idx, row in enumerate(rows, 1):
        inst_id = str(row.get("inst_id"))
        checked = 0
        repaired = 0
        failed = 0
        ignored = 0
        missing_before = 0
        missing_after = 0
        ignored_missing_after = 0
        for item_date in iter_dates(start_date, end_date):
            expected = expected_timestamps(row, item_date)
            if not expected:
                continue
            report = repair_date(args, client, store, raw_store, row, item_date, retry_config)
            checked += 1
            missing_before += report.missing_before
            missing_after += report.missing_after
            ignored_missing_after += report.ignored_missing_after
            if report.status == "repaired":
                repaired += 1
            elif report.status == "ignored_listing_edge":
                ignored += 1
            elif report.status == "failed":
                failed += 1
            reports.append(report)
        print(
            f"[{idx}/{len(rows)}] {inst_id}: checked={checked} repaired={repaired} "
            f"ignored={ignored} failed={failed} missing_before={missing_before} "
            f"missing_after={missing_after} ignored_missing_after={ignored_missing_after}",
            flush=True,
        )

    write_repair_report(
        args.catalog,
        reports,
        {
            "source": args.source,
            "start": date_text(start_date),
            "end": date_text(end_date),
            "normalized_root": str(args.normalized_root),
            "strict": args.strict,
        },
    )
    remaining = sum(item.missing_after for item in reports)
    ignored_remaining = sum(item.ignored_missing_after for item in reports)
    failed_dates = sum(1 for item in reports if item.status == "failed")
    ignored_dates = sum(1 for item in reports if item.status == "ignored_listing_edge")
    print(
        f"coverage repair done: checked={len(reports)} repaired_dates="
        f"{sum(1 for item in reports if item.status == 'repaired')} "
        f"ignored_dates={ignored_dates} failed_dates={failed_dates} "
        f"missing_after={remaining} ignored_missing_after={ignored_remaining} catalog={args.catalog}",
        flush=True,
    )
    if args.strict and remaining > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
