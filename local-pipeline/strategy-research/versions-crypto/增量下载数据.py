#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量下载数据

用途：给 strategy-research/versions-crypto 下的研究脚本补最新K线数据。
逻辑：默认调用 crypto-v2/scripts/data_update_okx.py，只重刷最近300根1m并重聚合5m/15m/1H。
      只有明确传 --backfill-history 或 --pages，才调用历史补全 data_backfill_okx.py。

说明：只更新本地研究数据，不下单，不影响正在跑的实盘 bot。
常用：
  python3 增量下载数据.py --check
  python3 增量下载数据.py
  python3 增量下载数据.py --symbol-limit 50
  python3 增量下载数据.py --backfill-history --pages 20
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
当前目录 = Path(__file__).resolve().parent
项目根目录 = 当前目录.parents[2]
本地流水线目录 = 项目根目录 / "local-pipeline"
crypto_v2目录 = 本地流水线目录 / "crypto-v2"
标准化数据目录 = 项目根目录 / "data/normalized_gzip"
原始数据目录 = 项目根目录 / "data/raw/okx"
更新质量文件 = 项目根目录 / "data/catalog/okx_1m_update_quality.json"
回填质量文件 = 项目根目录 / "data/catalog/okx_1m_quality.json"
下载状态文件 = 项目根目录 / "data/catalog/download_state.json"
合约维表 = 项目根目录 / "data/catalog/instruments_okx_usdt_swap_dim.json"
合约快照目录 = 项目根目录 / "data/catalog/instrument_snapshots/okx_swap"
合约同步脚本 = crypto_v2目录 / "scripts/sync_okx_instruments.py"
增量刷新脚本 = crypto_v2目录 / "scripts/data_update_okx.py"
历史补全脚本 = crypto_v2目录 / "scripts/data_backfill_okx.py"
品种清单 = 项目根目录 / "data/catalog/symbols_usdt_swap.json"

sys.path.insert(0, str(crypto_v2目录 / "src"))
from cryptov2.data.coverage import summarize_range_coverage
from cryptov2.data.instruments_dim import select_instrument_symbols


def 今天() -> datetime.date:
    return datetime.now(CST).date()


def 最新数据日期(bar: str = "5m"):
    root = 标准化数据目录 / f"candles_{bar}"
    if not root.exists():
        return None
    dates = []
    for p in root.glob("date=*"):
        text = p.name.replace("date=", "")
        try:
            dates.append(datetime.strptime(text, "%Y-%m-%d").date())
        except ValueError:
            pass
    return max(dates) if dates else None


def 日期文件数量(bar: str, date_value=None) -> int:
    if date_value is None:
        return 0
    root = 标准化数据目录 / f"candles_{bar}" / f"date={date_value:%Y-%m-%d}"
    if not root.exists():
        return 0
    return sum(1 for p in root.rglob("*") if p.is_file())


def 预期品种数量() -> int | None:
    if 合约维表.exists():
        try:
            return len(select_instrument_symbols(合约维表, online_only=True))
        except Exception:
            pass
    try:
        obj = json.loads(品种清单.read_text(encoding="utf-8"))
    except Exception:
        return None
    symbols = obj.get("symbols") if isinstance(obj, dict) else None
    return len(symbols) if isinstance(symbols, list) else None


def 估算页数(latest_date, min_pages: int, max_pages: int) -> int:
    if latest_date is None:
        return max_pages
    now = datetime.now(CST)
    start = datetime.combine(latest_date, datetime.min.time(), tzinfo=CST)
    gap_minutes = max(0, (now - start).total_seconds() / 60)
    # 每页约300根1m，额外加半天缓冲，避免边界缺K。
    pages = math.ceil((gap_minutes + 12 * 60) / 300)
    return max(min_pages, min(max_pages, pages))


def run(cmd: list[str]) -> int:
    print("执行:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(crypto_v2目录))


def 同步合约维表(args) -> int:
    if args.no_sync_instruments:
        print("跳过合约维表同步。")
        return 0
    cmd = [
        sys.executable,
        str(合约同步脚本),
        "--source", args.source,
        "--timeout", str(args.timeout),
        "--dim-catalog", str(合约维表),
        "--legacy-symbol-catalog", str(品种清单),
        "--snapshot-dir", str(合约快照目录),
    ]
    if args.base_url:
        cmd += ["--base-url", args.base_url]
    return run(cmd)


def 最近完整日覆盖缺口(latest_date, today, days: int, threshold: float):
    if latest_date is None or not 合约维表.exists():
        return []
    expected_symbols = select_instrument_symbols(合约维表, online_only=True)
    if not expected_symbols:
        return []

    # 今天的分区天然是盘中不完整；覆盖率闸门只检查最近已经结束的日期。
    end_date = min(latest_date, today - timedelta(days=1))
    if days <= 0 or end_date < today - timedelta(days=3650):
        return []
    start_date = end_date - timedelta(days=days - 1)
    reports = summarize_range_coverage(
        标准化数据目录,
        bar="5m",
        start=start_date,
        end=end_date,
        expected_symbols=expected_symbols,
    )
    bad = [item for item in reports if item.full_ratio < threshold]
    if reports:
        print("最近完整日5m覆盖率:")
        for item in reports:
            print(
                f"  {item.date}: expected={item.expected_symbols} "
                f"present={item.present_symbols} full={item.full_symbols} "
                f"partial={item.partial_symbols} missing={item.missing_symbols} "
                f"ratio={item.full_ratio:.3f}"
            )
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description="增量下载 crypto-v2 最新K线数据")
    parser.add_argument("--check", action="store_true", help="只检查最新日期，不下载")
    parser.add_argument("--force", action="store_true", help="即使数据已到今天，也强制刷新")
    parser.add_argument("--backfill-history", action="store_true", help="明确做历史补全；默认不使用")
    parser.add_argument("--pages", type=int, default=None, help="历史补全页数；每页约300分钟，设置后等同 --backfill-history")
    parser.add_argument("--limit", type=int, default=300, help="默认增量刷新最近N根1m，最大300")
    parser.add_argument("--min-pages", type=int, default=3, help="自动估算时最少页数")
    parser.add_argument("--max-pages", type=int, default=30, help="自动估算时最多页数")
    parser.add_argument("--symbol-limit", type=int, default=None, help="只更新前N个品种，用于快速测试")
    parser.add_argument("--symbols", nargs="*", default=[], help="只更新指定品种，如 BTC-USDT-SWAP")
    parser.add_argument("--sleep", type=float, default=0.05, help="请求间隔秒")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--source", choices=["okx", "relay"], default="okx", help="行情源；relay 需要 OKX_RELAY_BASE_URL 或 --base-url")
    parser.add_argument("--base-url", default=None, help="覆盖行情源 base URL")
    parser.add_argument("--no-sync-instruments", action="store_true", help="跳过部署前合约维表同步")
    parser.add_argument("--coverage-days", type=int, default=3, help="检查最近N个完整日覆盖率")
    parser.add_argument("--coverage-threshold", type=float, default=0.95, help="完整合约覆盖率低于该值视为缺口")
    parser.add_argument("--no-auto-backfill-gaps", action="store_true", help="发现最近完整日缺口时不自动切换历史补全")
    parser.add_argument("--strict-coverage", action="store_true", help="覆盖率不达标且不自动补全时直接失败")
    args = parser.parse_args()

    rc = 同步合约维表(args)
    if rc != 0:
        return rc

    latest_5m = 最新数据日期("5m")
    latest_1m = 最新数据日期("1m")
    latest_1h = 最新数据日期("1H")
    today = 今天()
    expected_symbols = 预期品种数量()
    latest_5m_files = 日期文件数量("5m", latest_5m)
    print(f"本地1m最新日期: {latest_1m}")
    print(f"本地5m最新日期: {latest_5m}")
    print(f"本地1H最新日期: {latest_1h}")
    print(f"本地5m最新日期文件数: {latest_5m_files}")
    if expected_symbols:
        print(f"预期合约品种数: {expected_symbols}")
    print(f"今天(CST): {today}")
    coverage_bad = 最近完整日覆盖缺口(
        latest_5m,
        today,
        args.coverage_days,
        args.coverage_threshold,
    )
    if coverage_bad:
        dates = ", ".join(item.date for item in coverage_bad)
        print(f"发现最近完整日覆盖率不足: {dates}")

    today_partial = (
        latest_5m == today
        and expected_symbols is not None
        and latest_5m_files < int(expected_symbols * 0.9)
    )
    if today_partial:
        print("今天数据目录已存在但文件数明显不完整，将继续增量补齐。")

    need_update = args.force or latest_5m is None or latest_5m < today or today_partial or bool(coverage_bad)
    if args.check:
        print("需要更新" if need_update else "数据已到今天")
        return 0
    if not need_update:
        print("数据已到今天，跳过下载。需要强刷可加 --force")
        return 0

    auto_backfill_gaps = bool(coverage_bad) and not args.no_auto_backfill_gaps
    if coverage_bad and args.strict_coverage and not auto_backfill_gaps:
        print("覆盖率不达标，已按 --strict-coverage 停止。")
        return 1

    use_backfill = args.backfill_history or args.pages is not None or auto_backfill_gaps
    if use_backfill:
        earliest_bad = min(
            (datetime.strptime(item.date, "%Y-%m-%d").date() for item in coverage_bad),
            default=latest_5m,
        )
        estimate_from = earliest_bad if auto_backfill_gaps else latest_5m
        pages = args.pages if args.pages is not None else 估算页数(estimate_from, args.min_pages, args.max_pages)
        print("模式: 历史补全 backfill。由 --backfill-history/--pages 或覆盖率缺口自动触发。")
        cmd = [
            sys.executable,
            str(历史补全脚本),
            "--source", args.source,
            "--pages", str(pages),
            "--store-backend", "gzip_partition",
            "--normalized-root", str(标准化数据目录),
            "--raw-root", str(原始数据目录),
            "--catalog", str(回填质量文件),
            "--state", str(下载状态文件),
            "--sleep", str(args.sleep),
            "--timeout", str(args.timeout),
            "--retry-attempts", "3",
            "--retry-base-sleep", "5",
            "--retry-max-sleep", "30",
            "--resume",
            "--dim-catalog", str(合约维表),
            "--symbol-catalog", str(品种清单),
            "--snapshot-dir", str(合约快照目录),
            "--no-sync-instruments",
        ]
    else:
        print("模式: 最近增量刷新 update，按 crypto-v2 架构只重刷最近1m K线并重聚合5m/15m/1H。")
        if latest_5m is not None and latest_5m < today:
            print("提示: 本地日期落后今天；默认 update 只覆盖最近300根1m。若确实断档多天，再手动加 --backfill-history。")
        cmd = [
            sys.executable,
            str(增量刷新脚本),
            "--source", args.source,
            "--limit", str(args.limit),
            "--store-backend", "gzip_partition",
            "--normalized-root", str(标准化数据目录),
            "--raw-root", str(原始数据目录),
            "--catalog", str(更新质量文件),
            "--state", str(下载状态文件),
            "--sleep", str(args.sleep),
            "--timeout", str(args.timeout),
            "--dim-catalog", str(合约维表),
            "--symbol-catalog", str(品种清单),
            "--snapshot-dir", str(合约快照目录),
            "--no-sync-instruments",
        ]
    if args.base_url:
        cmd += ["--base-url", args.base_url]
    if args.symbol_limit:
        cmd += ["--symbol-limit", str(args.symbol_limit)]
    if args.symbols:
        cmd += ["--symbols", *args.symbols]

    rc = run(cmd)
    print(f"数据脚本退出码: {rc}")
    print(f"更新后5m最新日期: {最新数据日期('5m')}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
