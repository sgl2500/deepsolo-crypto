#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import settings  # noqa: E402


def _ok(label: str, message: str) -> None:
    print(f"[OK]   {label}: {message}")


def _warn(label: str, message: str) -> None:
    print(f"[WARN] {label}: {message}")


def _fail(label: str, message: str) -> None:
    print(f"[FAIL] {label}: {message}")


def _check_path(label: str, path: Path) -> bool:
    if path.exists():
        _ok(label, str(path))
        return True
    _warn(label, f"not found: {path}")
    return False


def _check_writable_dir(label: str, path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        _fail(label, f"not writable: {path} ({exc})")
        return False
    _ok(label, f"writable: {path}")
    return True


def _latest_partition(timeframe: str, dirname: str) -> bool:
    base = settings.DATA_ROOT / dirname
    if not base.exists():
        _warn(f"{timeframe} data", f"missing directory: {base}")
        return False

    date_dirs = [p for p in base.iterdir() if p.is_dir() and p.name.startswith("date=")]
    if not date_dirs:
        _warn(f"{timeframe} data", f"no date=* partitions under {base}")
        return False

    latest = max(date_dirs, key=lambda item: item.name)
    file_count = sum(1 for _ in latest.glob("*.csv.gz"))
    date_value = latest.name.removeprefix("date=")
    _ok(f"{timeframe} data", f"latest date={date_value}, files={file_count}, path={latest}")
    return file_count > 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local crypto screener environment paths.")
    parser.add_argument("--strict", action="store_true", help="return non-zero when critical paths are missing")
    args = parser.parse_args()

    print("数字币选币环境诊断")
    print("=" * 28)

    print(f"Project root: {settings.PROJECT_ROOT}")
    print(f"App timezone: {settings.APP_TIMEZONE}")
    print(f"Data root:    {settings.DATA_ROOT}")
    print(f"Runtime root: {settings.RUNTIME_ROOT}")
    print(f"Legacy data update pipeline: {settings.USE_LEGACY_PIPELINE}")
    print()

    critical_ok = True
    critical_ok &= _check_path("DATA_ROOT", settings.DATA_ROOT)
    critical_ok &= _check_writable_dir("RUNTIME_ROOT", settings.RUNTIME_ROOT)

    _check_path("CATALOG_ROOT", settings.CATALOG_ROOT)
    _check_path("CRYPTO_V2_ROOT", settings.CRYPTO_V2_ROOT)
    _check_path("STRATEGY_RESEARCH_ROOT", settings.STRATEGY_RESEARCH_ROOT)

    update_script = settings.STRATEGY_RESEARCH_ROOT / "versions-crypto" / "增量下载数据.py"
    daily_script = settings.CRYPTO_V2_ROOT / "scripts" / "build_daily_bars.py"
    _check_path("Update script", update_script)
    _check_path("Daily script", daily_script)

    for label, path in (
        ("Backtest DB parent", settings.BACKTEST_DB_PATH.parent),
        ("Favorites DB parent", settings.SCREENER_FAVORITES_DB_PATH.parent),
        ("Indicator store parent", settings.INDICATOR_STORE_PATH.parent),
        ("Script indicator root", settings.SCRIPT_INDICATOR_ROOT),
        ("Contract update runtime", settings.CONTRACT_UPDATE_RUNTIME_DIR),
    ):
        _check_writable_dir(label, path)

    print()
    print("K线分区")
    print("-" * 28)
    has_any_partition = False
    for timeframe, dirname in settings.TIMEFRAMES.items():
        has_any_partition = _latest_partition(timeframe, dirname) or has_any_partition

    print()
    if args.strict and (not critical_ok or not has_any_partition):
        _fail("Result", "strict mode failed")
        return 1
    _ok("Result", "diagnostic completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
