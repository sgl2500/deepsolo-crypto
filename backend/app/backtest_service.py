from __future__ import annotations

import csv
import gzip
import json
import math
import os
import sqlite3
import time
import uuid
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import APP_TIMEZONE, TIMEFRAMES
from .data_source import data_source_service
from .favorite_repository import screener_favorite_repository
from .screener import query_screener

ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("BACKTEST_DB", ROOT_DIR / ".runtime" / "backtests.sqlite3"))
MAX_CHECKPOINTS = 500


@dataclass(frozen=True)
class PriceBar:
    ts: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class PriceSeries:
    bars: list[PriceBar]
    timestamps: list[int]


class BacktestService:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        favorite = self._favorite(payload.get("favorite_id"))
        config = self._normalize_config(payload, favorite)
        run_id = uuid.uuid4().hex
        now = _now_ms()
        name = config.get("name") or f"{favorite['name']} 回测 {config['start_date']}~{config['end_date']}"

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_runs (
                    id, name, favorite_id, status, config, result, error,
                    created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    name,
                    favorite["id"],
                    "running",
                    json.dumps(config, ensure_ascii=False, separators=(",", ":")),
                    "",
                    "",
                    now,
                    now,
                    None,
                ),
            )

        try:
            result = self._execute(config, favorite)
            status = "completed"
            error = ""
        except Exception as exc:  # Keep failed runs visible in the UI.
            result = None
            status = "failed"
            error = str(exc)

        finished_at = _now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE backtest_runs
                SET status = ?, result = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")) if result else "",
                    error,
                    finished_at,
                    run_id,
                ),
            )
        item = self.get_run(run_id)
        if item is None:
            raise RuntimeError("回测运行记录写入失败")
        return item

    def list_runs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, favorite_id, status, config, result, error,
                       created_at, started_at, finished_at
                FROM backtest_runs
                ORDER BY created_at DESC
                LIMIT 100
                """
            ).fetchall()
        return [self._row_to_item(row, compact=True) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, favorite_id, status, config, result, error,
                       created_at, started_at, finished_at
                FROM backtest_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return self._row_to_item(row, compact=False) if row else None

    def _execute(self, config: dict[str, Any], favorite: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        signal_timeframe = config["signal_timeframe"]
        entry_timeframe = config["entry_timeframe"]
        checkpoints = self._checkpoints(config)
        if not checkpoints:
            raise ValueError("回测区间内没有可用异动扫描 K 线")

        trade_dates = self._trade_dates(
            entry_timeframe,
            config["start_date"],
            config["end_date"],
            config["hold_hours"],
        )
        if not trade_dates:
            raise ValueError("回测区间内没有可用成交 K 线")

        metadata_filters = _favorite_metadata_filters(favorite)
        price_cache: dict[tuple[str, str], PriceSeries] = {}
        script_cache: dict[tuple[str, str, str], dict[str, list[dict[str, str]]]] = {}
        open_positions: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        checkpoint_summaries: list[dict[str, Any]] = []
        counters = {
            "checkpoints": len(checkpoints),
            "matched_signals": 0,
            "opened_trades": 0,
            "skipped_overlap": 0,
            "skipped_max_positions": 0,
            "skipped_no_entry": 0,
            "skipped_no_exit": 0,
        }

        for checkpoint_index, checkpoint in enumerate(checkpoints, start=1):
            signal_ts = checkpoint["signal_ts"]
            open_positions = [item for item in open_positions if int(item["exit_ts"]) > signal_ts]
            open_symbols = {str(item["inst_id"]) for item in open_positions}

            response = query_screener(
                timeframe=signal_timeframe,
                date=checkpoint["date"],
                as_of=_format_iso(checkpoint["as_of_ts"]),
                min_ret_15m=_optional_float(favorite.get("min_ret_15m")),
                min_vol_ratio_60=_optional_float(favorite.get("min_vol_ratio_60")),
                min_vol_quote_15m=_optional_float(favorite.get("min_vol_quote_15m")),
                sort_by=str(favorite.get("sort_by") or "ret_15m"),
                sort_dir="desc",
                metadata_filters=metadata_filters,
                limit=500,
                script_values_cache=script_cache,
            )
            rows = response.get("rows", [])
            counters["matched_signals"] += len(rows)
            opened_here = 0

            for row in rows:
                inst_id = str(row.get("inst_id") or "")
                if not inst_id:
                    continue
                if inst_id in open_symbols:
                    counters["skipped_overlap"] += 1
                    continue
                if len(open_positions) >= config["max_positions"]:
                    counters["skipped_max_positions"] += 1
                    continue

                series = price_cache.get((entry_timeframe, inst_id))
                if series is None:
                    series = self._price_series(entry_timeframe, inst_id, trade_dates)
                    price_cache[(entry_timeframe, inst_id)] = series

                trade, skip_reason = self._build_trade(
                    run_index=len(trades) + 1,
                    checkpoint=checkpoint,
                    row=row,
                    series=series,
                    config=config,
                )
                if trade is None:
                    if skip_reason == "no_exit":
                        counters["skipped_no_exit"] += 1
                    else:
                        counters["skipped_no_entry"] += 1
                    continue

                trades.append(trade)
                open_positions.append({"inst_id": inst_id, "exit_ts": trade["exit_ts"]})
                open_symbols.add(inst_id)
                counters["opened_trades"] += 1
                opened_here += 1

            checkpoint_summaries.append(
                {
                    "index": checkpoint_index,
                    "date": checkpoint["date"],
                    "as_of_ts": checkpoint["as_of_ts"],
                    "as_of_time": _format_time(checkpoint["as_of_ts"]),
                    "signal_ts": signal_ts,
                    "signal_time": _format_time(signal_ts),
                    "matched_count": int(response.get("matched_count") or len(rows)),
                    "opened_count": opened_here,
                    "duration_ms": int(response.get("duration_ms") or 0),
                }
            )

        summary, equity = self._summarize(config, counters, trades, checkpoints)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        summary["duration_ms"] = elapsed_ms
        return {
            "summary": summary,
            "equity": equity,
            "trades": trades,
            "checkpoints": checkpoint_summaries,
            "favorite": {
                "id": favorite["id"],
                "name": favorite["name"],
                "timeframe": favorite.get("timeframe"),
                "condition_count": favorite.get("condition_count", len(metadata_filters)),
            },
        }

    def _build_trade(
        self,
        *,
        run_index: int,
        checkpoint: dict[str, Any],
        row: dict[str, Any],
        series: PriceSeries,
        config: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        entry_bar = _bar_at_or_after(series, checkpoint["signal_ts"])
        if entry_bar is None:
            return None, "no_entry"
        exit_target_ts = entry_bar.ts + int(config["hold_hours"] * 60 * 60 * 1000)
        exit_bar = _bar_at_or_after(series, exit_target_ts)
        if exit_bar is None:
            return None, "no_exit"

        position_usdt = float(config["position_usdt"])
        fee_rate = float(config["fee_bps_per_side"]) / 10000
        slippage_rate = float(config["slippage_bps_per_side"]) / 10000
        raw_entry = entry_bar.open
        raw_exit = exit_bar.open
        entry_price = raw_entry * (1 + slippage_rate)
        exit_price = raw_exit * (1 - slippage_rate)
        gross_return = exit_price / entry_price - 1
        fee_usdt = position_usdt * fee_rate * 2
        gross_pnl = position_usdt * gross_return
        pnl_usdt = gross_pnl - fee_usdt
        net_return_pct = pnl_usdt / position_usdt * 100 if position_usdt else 0

        return (
            {
                "id": run_index,
                "inst_id": row.get("inst_id"),
                "signal_date": checkpoint["date"],
                "signal_ts": checkpoint["signal_ts"],
                "signal_time": _format_time(checkpoint["signal_ts"]),
                "entry_ts": entry_bar.ts,
                "entry_time": _format_time(entry_bar.ts),
                "exit_ts": exit_bar.ts,
                "exit_time": _format_time(exit_bar.ts),
                "hold_hours": config["hold_hours"],
                "position_usdt": _round(position_usdt, 4),
                "raw_entry_price": _round(raw_entry, 10),
                "raw_exit_price": _round(raw_exit, 10),
                "entry_price": _round(entry_price, 10),
                "exit_price": _round(exit_price, 10),
                "gross_return_pct": _round(gross_return * 100, 4),
                "net_return_pct": _round(net_return_pct, 4),
                "fee_usdt": _round(fee_usdt, 4),
                "pnl_usdt": _round(pnl_usdt, 4),
                "matched_conditions": row.get("matched_conditions", []),
                "signal_metrics": {
                    "latest_close": row.get("latest_close"),
                    "ret_15m": row.get("ret_15m"),
                    "ret_1h": row.get("ret_1h"),
                    "vol_quote_15m": row.get("vol_quote_15m"),
                    "vol_ratio_60": row.get("vol_ratio_60"),
                },
            },
            "",
        )

    def _summarize(
        self,
        config: dict[str, Any],
        counters: dict[str, int],
        trades: list[dict[str, Any]],
        checkpoints: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        sorted_trades = sorted(trades, key=lambda item: (int(item["exit_ts"]), int(item["id"])))
        initial_capital = float(config["position_usdt"]) * int(config["max_positions"])
        equity_value = initial_capital
        peak = initial_capital
        max_drawdown_pct = 0.0
        equity = [
            {
                "ts": checkpoints[0]["signal_ts"] if checkpoints else None,
                "time": _format_time(checkpoints[0]["signal_ts"]) if checkpoints else None,
                "equity": _round(equity_value, 4),
                "pnl_usdt": 0,
                "drawdown_pct": 0,
            }
        ]
        total_pnl = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        wins = 0

        for trade in sorted_trades:
            pnl = float(trade.get("pnl_usdt") or 0)
            total_pnl += pnl
            equity_value = initial_capital + total_pnl
            peak = max(peak, equity_value)
            drawdown_pct = (equity_value / peak - 1) * 100 if peak else 0
            max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
            if pnl > 0:
                wins += 1
                gross_profit += pnl
            elif pnl < 0:
                gross_loss += abs(pnl)
            equity.append(
                {
                    "ts": trade["exit_ts"],
                    "time": trade["exit_time"],
                    "equity": _round(equity_value, 4),
                    "pnl_usdt": _round(total_pnl, 4),
                    "drawdown_pct": _round(drawdown_pct, 4),
                }
            )

        trade_count = len(trades)
        return_pct = total_pnl / initial_capital * 100 if initial_capital else 0
        avg_pnl = total_pnl / trade_count if trade_count else 0
        summary = {
            **counters,
            "start_date": config["start_date"],
            "end_date": config["end_date"],
            "signal_mode": config["signal_mode"],
            "signal_timeframe": config["signal_timeframe"],
            "entry_timeframe": config["entry_timeframe"],
            "hold_hours": config["hold_hours"],
            "initial_capital": _round(initial_capital, 4),
            "total_trades": trade_count,
            "win_trades": wins,
            "loss_trades": sum(1 for trade in trades if float(trade.get("pnl_usdt") or 0) < 0),
            "win_rate": _round(wins / trade_count * 100, 4) if trade_count else 0,
            "total_pnl": _round(total_pnl, 4),
            "total_return_pct": _round(return_pct, 4),
            "avg_pnl": _round(avg_pnl, 4),
            "profit_factor": _round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
            "max_drawdown_pct": _round(max_drawdown_pct, 4),
            "fee_bps_per_side": config["fee_bps_per_side"],
            "slippage_bps_per_side": config["slippage_bps_per_side"],
        }
        return summary, equity

    def _checkpoints(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        signal_timeframe = config["signal_timeframe"]
        period_ms = _period_ms(signal_timeframe)
        dates = [
            item
            for item in _available_dates(signal_timeframe)
            if config["start_date"] <= item <= config["end_date"]
        ]
        checkpoints: list[dict[str, Any]] = []
        for item_date in dates:
            bars = self._sample_bars(signal_timeframe, item_date)
            if not bars:
                continue
            selected = [bars[-1]] if config["signal_mode"] == "daily" else bars
            for bar in selected:
                checkpoints.append(
                    {
                        "date": item_date,
                        "as_of_ts": bar.ts,
                        "signal_ts": bar.ts + period_ms,
                    }
                )
        checkpoints.sort(key=lambda item: (item["signal_ts"], item["date"]))
        checkpoint_limit = int(config.get("checkpoint_limit") or MAX_CHECKPOINTS)
        if len(checkpoints) > checkpoint_limit:
            raise ValueError(
                f"异动扫描检查点过多：{len(checkpoints)} 个，当前上限 {checkpoint_limit}；请缩短日期区间或改为每日一次。"
            )
        return checkpoints

    def _sample_bars(self, timeframe: str, item_date: str) -> list[PriceBar]:
        files = data_source_service.contract_files(timeframe, item_date)
        if not files:
            return []
        preferred_names = ("BTC-USDT-SWAP.csv.gz", "ETH-USDT-SWAP.csv.gz")
        path = next((item for item in files if item.name in preferred_names), files[0])
        return _read_price_bars(path)

    def _trade_dates(self, timeframe: str, start_date: str, end_date: str, hold_hours: int) -> list[str]:
        end_buffer = Date.fromisoformat(end_date) + timedelta(days=math.ceil(hold_hours / 24) + 3)
        end_text = end_buffer.isoformat()
        return [item for item in _available_dates(timeframe) if start_date <= item <= end_text]

    def _price_series(self, timeframe: str, inst_id: str, dates: list[str]) -> PriceSeries:
        bars: list[PriceBar] = []
        for item_date in dates:
            path = _contract_path(timeframe, item_date, inst_id)
            if path.exists():
                bars.extend(_read_price_bars(path))
        bars.sort(key=lambda item: item.ts)
        deduped: list[PriceBar] = []
        last_ts: int | None = None
        for bar in bars:
            if last_ts == bar.ts:
                deduped[-1] = bar
            else:
                deduped.append(bar)
                last_ts = bar.ts
        return PriceSeries(bars=deduped, timestamps=[item.ts for item in deduped])

    def _favorite(self, favorite_id: Any) -> dict[str, Any]:
        normalized = str(favorite_id or "").strip()
        if not normalized:
            raise ValueError("请选择要回测的收藏条件")
        favorite = screener_favorite_repository.get(normalized)
        if not favorite:
            raise KeyError(f"收藏条件不存在：{normalized}")
        return favorite

    def _normalize_config(self, payload: dict[str, Any], favorite: dict[str, Any]) -> dict[str, Any]:
        start_date = _validate_date(str(payload.get("start_date") or ""), "开始日期")
        end_date = _validate_date(str(payload.get("end_date") or ""), "结束日期")
        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")

        signal_mode = str(payload.get("signal_mode") or "daily")
        if signal_mode == "hourly":
            signal_mode = "each_bar_close"
        if signal_mode not in {"daily", "each_bar_close"}:
            raise ValueError("异动扫描频率只支持 daily 或 each_bar_close")

        signal_timeframe = _normalize_timeframe(str(payload.get("signal_timeframe") or favorite.get("timeframe") or "1H"))
        entry_timeframe = _normalize_timeframe(str(payload.get("entry_timeframe") or "1m"))
        if signal_mode == "each_bar_close" and _period_ms(signal_timeframe) >= 24 * 60 * 60 * 1000:
            raise ValueError("逐根K线扫描不支持日线周期，请选择 1H/5m/1m 或改为每日一次")

        return {
            "favorite_id": favorite["id"],
            "favorite_name": favorite["name"],
            "name": str(payload.get("name") or "").strip(),
            "start_date": start_date,
            "end_date": end_date,
            "signal_timeframe": signal_timeframe,
            "signal_mode": signal_mode,
            "entry_timeframe": entry_timeframe,
            "hold_hours": _bounded_int(payload.get("hold_hours"), 24, 1, 720, "持仓小时数"),
            "position_usdt": _bounded_float(payload.get("position_usdt"), 100.0, 1.0, 1_000_000.0, "单笔金额"),
            "max_positions": _bounded_int(payload.get("max_positions"), 5, 1, 100, "最大持仓数"),
            "fee_bps_per_side": _bounded_float(payload.get("fee_bps_per_side"), 5.0, 0.0, 1000.0, "单边手续费bps"),
            "slippage_bps_per_side": _bounded_float(payload.get("slippage_bps_per_side"), 5.0, 0.0, 1000.0, "单边滑点bps"),
            "checkpoint_limit": _bounded_int(payload.get("checkpoint_limit"), MAX_CHECKPOINTS, 1, 5000, "检查点上限"),
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    favorite_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config TEXT NOT NULL,
                    result TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    started_at INTEGER,
                    finished_at INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_backtest_runs_created_at
                ON backtest_runs(created_at DESC)
                """
            )

    def _row_to_item(self, row: sqlite3.Row, *, compact: bool) -> dict[str, Any]:
        config = _loads_json(row["config"], {})
        result = _loads_json(row["result"], None) if row["result"] else None
        if compact and isinstance(result, dict):
            result = {
                "summary": result.get("summary"),
                "equity": (result.get("equity") or [])[-30:],
                "daily_equity": (result.get("daily_equity") or result.get("equity") or [])[-30:],
                "trades": [],
                "favorite": result.get("favorite"),
                "signal_set": result.get("signal_set"),
            }
        return {
            "id": row["id"],
            "name": row["name"],
            "favorite_id": row["favorite_id"],
            "status": row["status"],
            "config": config,
            "result": result,
            "error": row["error"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }


def _favorite_metadata_filters(favorite: dict[str, Any]) -> list[dict[str, Any]]:
    filters = []
    for condition in favorite.get("metadata_conditions") or []:
        if not isinstance(condition, dict):
            continue
        filters.append(
            {
                "indicator_id": condition.get("indicator_id") or (condition.get("indicator") or {}).get("id"),
                "operator": condition.get("operator") or "any_not_empty",
                "value": condition.get("value") or "",
                "time_mode": condition.get("time_mode") or "previous_trading_day",
                "time_offset": condition.get("time_offset") or "1",
                "time_point_mode": condition.get("time_point_mode") or "",
                "time_point": condition.get("time_point") or "",
                "bar_offset": condition.get("bar_offset") or "0",
                "time_offset_value": condition.get("time_offset_value") or "0",
                "time_offset_unit": condition.get("time_offset_unit") or "hour",
                "truncate_mode": condition.get("truncate_mode") or "none",
                "truncate_count": condition.get("truncate_count") or "",
                "external_relation": bool(condition.get("external_relation")),
                "time_range": bool(condition.get("time_range")),
                "exclude": bool(condition.get("exclude")),
                "match_current_bar": bool(condition.get("match_current_bar")),
            }
        )
    return filters


def _available_dates(timeframe: str) -> list[str]:
    tf_dir = data_source_service.root / TIMEFRAMES[_normalize_timeframe(timeframe)]
    if not tf_dir.exists():
        return []
    dates = []
    for entry in tf_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("date="):
            dates.append(entry.name.split("date=", 1)[1])
    return sorted(dates)


def _contract_path(timeframe: str, item_date: str, inst_id: str) -> Path:
    return data_source_service.root / TIMEFRAMES[_normalize_timeframe(timeframe)] / f"date={item_date}" / f"{inst_id}.csv.gz"


def _read_price_bars(path: Path) -> list[PriceBar]:
    bars: list[PriceBar] = []
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ts = _to_int(row.get("ts"))
            close = _to_float(row.get("close"))
            if ts is None or close is None or close <= 0:
                continue
            open_price = _to_float(row.get("open")) or close
            bars.append(
                PriceBar(
                    ts=ts,
                    open=open_price,
                    high=_to_float(row.get("high")) or max(open_price, close),
                    low=_to_float(row.get("low")) or min(open_price, close),
                    close=close,
                )
            )
    return bars


def _bar_at_or_after(series: PriceSeries, target_ts: int) -> PriceBar | None:
    index = bisect_left(series.timestamps, target_ts)
    if index >= len(series.bars):
        return None
    return series.bars[index]


def _normalize_timeframe(value: str) -> str:
    for key in TIMEFRAMES:
        if key.lower() == value.lower():
            return key
    raise ValueError(f"不支持的周期：{value}")


def _period_ms(timeframe: str) -> int:
    normalized = _normalize_timeframe(timeframe)
    unit = normalized[-1].lower()
    count = int(normalized[:-1])
    if unit == "m":
        return count * 60 * 1000
    if unit == "h":
        return count * 60 * 60 * 1000
    if unit == "d":
        return count * 24 * 60 * 60 * 1000
    raise ValueError(f"不支持的周期：{timeframe}")


def _validate_date(value: str, label: str) -> str:
    try:
        parsed = Date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}必须是 YYYY-MM-DD") from exc
    return parsed.isoformat()


def _bounded_int(value: Any, default: int, min_value: int, max_value: int, label: str) -> int:
    if value in (None, ""):
        parsed = default
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是整数") from exc
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"{label}必须在 {min_value}~{max_value} 之间")
    return parsed


def _bounded_float(value: Any, default: float, min_value: float, max_value: float, label: str) -> float:
    if value in (None, ""):
        parsed = default
    else:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是数字") from exc
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"{label}必须在 {min_value:g}~{max_value:g} 之间")
    return parsed


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _to_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _format_time(ts: int | None) -> str | None:
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts / 1000, tz=ZoneInfo(APP_TIMEZONE))
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_iso(ts: int) -> str:
    dt = datetime.fromtimestamp(ts / 1000, tz=ZoneInfo(APP_TIMEZONE))
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _round(value: float, digits: int) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(value, digits)


def _loads_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _now_ms() -> int:
    return int(time.time() * 1000)


backtest_service = BacktestService()
