#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRYPTO_V2_ROOT = ROOT / "local-pipeline" / "crypto-v2"
BACKFILL_SCRIPT = CRYPTO_V2_ROOT / "scripts" / "data_backfill_okx.py"
DAILY_SCRIPT = CRYPTO_V2_ROOT / "scripts" / "build_daily_bars.py"
DEFAULT_DATA_ROOT = ROOT / "data" / "normalized_gzip"
DEFAULT_CATALOG_ROOT = ROOT / "data" / "catalog"
DEFAULT_RAW_ROOT = ROOT / "data" / "raw" / "okx"

TIMEFRAMES = ("1m", "5m", "15m", "1H", "1D")


def resolve_path(raw: str | Path, *, base: Path = ROOT) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(raw))))
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def has_candle_files(root: Path) -> bool:
    return root.exists() and any(root.glob("candles_*/*/*.csv.gz"))


def timeframe_file_count(root: Path, timeframe: str) -> int:
    return sum(1 for _ in (root / f"candles_{timeframe}").glob("date=*/*.csv.gz"))


def latest_partition(root: Path, timeframe: str) -> str | None:
    folder = root / f"candles_{timeframe}"
    if not folder.exists():
        return None
    dates = sorted(path.name.removeprefix("date=") for path in folder.glob("date=*") if path.is_dir())
    return dates[-1] if dates else None


def history_pages_for_days(days: int, buffer_pages: int) -> int:
    minutes = max(1, days) * 24 * 60
    return math.ceil(minutes / 300) + max(0, buffer_pages)


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print()
    print("Running:", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=str(cwd), env=env)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def read_catalog(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def print_dataset_summary(root: Path) -> None:
    print()
    print("Dataset summary")
    print("-" * 40)
    for timeframe in TIMEFRAMES:
        print(
            f"{timeframe:>3}: files={timeframe_file_count(root, timeframe)} "
            f"latest={latest_partition(root, timeframe) or '-'}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize project-local real OKX data under ./data/normalized_gzip."
    )
    parser.add_argument("--days", type=int, default=5, help="Approximate calendar days of 1m history to download.")
    parser.add_argument("--buffer-pages", type=int, default=1, help="Extra OKX history pages beyond --days.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT, help="normalized_gzip output root.")
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG_ROOT, help="Local catalog output root.")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT, help="Raw OKX jsonl output root.")
    parser.add_argument("--symbols", nargs="*", default=[], help="Only download selected symbols, e.g. BTC-USDT-SWAP.")
    parser.add_argument("--symbol-limit", type=int, default=None, help="Only download the first N selected symbols.")
    parser.add_argument("--source", choices=["okx", "relay"], default="okx", help="Market data source.")
    parser.add_argument("--base-url", default=None, help="Override data source base URL.")
    parser.add_argument("--sleep", type=float, default=0.12, help="Sleep seconds between OKX history requests.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds.")
    parser.add_argument("--retry-attempts", type=int, default=6)
    parser.add_argument("--retry-base-sleep", type=float, default=10.0)
    parser.add_argument("--retry-max-sleep", type=float, default=60.0)
    parser.add_argument("--no-sync-instruments", action="store_true", help="Skip the OKX instrument dimension sync.")
    parser.add_argument("--resume", action="store_true", help="Continue an existing partial download.")
    parser.add_argument("--force", action="store_true", help="Delete --data-root before downloading.")
    parser.add_argument("--skip-daily", action="store_true", help="Skip building 1D candles from 1H candles.")
    parser.add_argument("--skip-doctor", action="store_true", help="Skip scripts/doctor.py after initialization.")
    parser.add_argument("--strict-errors", action="store_true", help="Fail when the backfill catalog reports symbol errors.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = resolve_path(args.data_root)
    catalog_root = resolve_path(args.catalog_root)
    raw_root = resolve_path(args.raw_root)

    if not BACKFILL_SCRIPT.exists() or not DAILY_SCRIPT.exists():
        raise SystemExit("Missing local-pipeline scripts. Check that local-pipeline/ is present in this checkout.")

    if args.force and data_root.exists():
        print(f"Deleting existing normalized data root: {data_root}")
        shutil.rmtree(data_root)

    if has_candle_files(data_root) and not args.resume:
        raise SystemExit(
            "Existing candle data was found. Refusing to modify it by default.\n"
            f"Data root: {data_root}\n"
            "Use --resume to continue/fill the existing dataset, or --force to rebuild this data root."
        )

    data_root.mkdir(parents=True, exist_ok=True)
    catalog_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    pages = history_pages_for_days(args.days, args.buffer_pages)
    quality_catalog = catalog_root / "okx_1m_quality.json"

    print("OKX data initialization")
    print("-" * 40)
    print(f"Project root:  {ROOT}")
    print(f"Data root:     {data_root}")
    print(f"Catalog root:  {catalog_root}")
    print(f"Raw root:      {raw_root}")
    print(f"Days:          {args.days}")
    print(f"History pages: {pages} (300 1m candles per page, plus recent candles)")
    print(f"Source:        {args.source}")
    if args.symbol_limit:
        print(f"Symbol limit:  {args.symbol_limit}")
    if args.symbols:
        print(f"Symbols:       {' '.join(args.symbols)}")

    backfill_cmd = [
        sys.executable,
        str(BACKFILL_SCRIPT),
        "--source",
        args.source,
        "--pages",
        str(pages),
        "--store-backend",
        "gzip_partition",
        "--normalized-root",
        str(data_root),
        "--raw-root",
        str(raw_root),
        "--catalog",
        str(quality_catalog),
        "--state",
        str(catalog_root / "download_state.json"),
        "--symbol-catalog",
        str(catalog_root / "symbols_usdt_swap.json"),
        "--dim-catalog",
        str(catalog_root / "instruments_okx_usdt_swap_dim.json"),
        "--snapshot-dir",
        str(catalog_root / "instrument_snapshots" / "okx_swap"),
        "--sleep",
        str(args.sleep),
        "--timeout",
        str(args.timeout),
        "--retry-attempts",
        str(args.retry_attempts),
        "--retry-base-sleep",
        str(args.retry_base_sleep),
        "--retry-max-sleep",
        str(args.retry_max_sleep),
    ]
    if args.resume:
        backfill_cmd.append("--resume")
    if args.no_sync_instruments:
        backfill_cmd.append("--no-sync-instruments")
    if args.base_url:
        backfill_cmd += ["--base-url", args.base_url]
    if args.symbol_limit:
        backfill_cmd += ["--symbol-limit", str(args.symbol_limit)]
    if args.symbols:
        backfill_cmd += ["--symbols", *args.symbols]

    run(backfill_cmd, cwd=CRYPTO_V2_ROOT)

    catalog = read_catalog(quality_catalog)
    summary = catalog.get("summary", {})
    errors = catalog.get("extra", {}).get("errors", [])
    if int(summary.get("rows_total") or 0) <= 0:
        raise SystemExit("No OKX candle rows were written. Check network access and OKX availability.")
    if errors:
        print(f"Warning: backfill reported {len(errors)} symbol errors. See {quality_catalog}")
        if args.strict_errors:
            raise SystemExit(1)

    if not args.skip_daily:
        daily_cmd = [
            sys.executable,
            str(DAILY_SCRIPT),
            "--store-backend",
            "gzip_partition",
            "--normalized-root",
            str(data_root),
            "--replace",
        ]
        if args.symbol_limit:
            daily_cmd += ["--symbol-limit", str(args.symbol_limit)]
        if args.symbols:
            daily_cmd += ["--symbols", *args.symbols]
        run(daily_cmd, cwd=CRYPTO_V2_ROOT)

    print_dataset_summary(data_root)

    required = ["1m", "5m", "15m", "1H"]
    if args.days >= 2 and not args.skip_daily:
        required.append("1D")
    missing = [timeframe for timeframe in required if timeframe_file_count(data_root, timeframe) == 0]
    if missing:
        raise SystemExit(f"Missing expected timeframe data after initialization: {', '.join(missing)}")

    if not args.skip_doctor:
        env = os.environ.copy()
        env["DATA_ROOT"] = str(data_root)
        env["CRYPTO_DATA_ROOT"] = str(data_root)
        env["CATALOG_ROOT"] = str(catalog_root)
        run([sys.executable, str(ROOT / "scripts" / "doctor.py"), "--strict"], env=env)

    print()
    print("OKX data initialization completed.")
    print("Start the app with:")
    print("./scripts/start-local.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
