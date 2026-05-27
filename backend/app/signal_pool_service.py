from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date as Date, timedelta
from pathlib import Path
from typing import Any

from .backtest_service import (
    DB_PATH,
    MAX_CHECKPOINTS,
    PriceBar,
    PriceSeries,
    _available_dates,
    _bar_at_or_after,
    _bounded_float,
    _bounded_int,
    _contract_path,
    _favorite_metadata_filters,
    _format_iso,
    _format_time,
    _loads_json,
    _normalize_timeframe,
    _now_ms,
    _optional_float,
    _period_ms,
    _read_price_bars,
    _round,
    _validate_date,
)
from . import script_indicator_service
from .data_source import data_source_service
from .favorite_repository import screener_favorite_repository
from .indicator_repository import indicator_repository
from .screener import query_screener

SIGNAL_EVENT_LIMIT = 500
BOT_LIKE_MAX_ENTRY_BARS = 12
MINUTE_MS = 60 * 1000


@dataclass(frozen=True)
class EntryCandidate:
    event: dict[str, Any]
    entry_bar: PriceBar
    trigger_pct: list[float]
    delay_min: float
    entry_reason: str


class SignalPoolService:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_signal_set(self, payload: dict[str, Any]) -> dict[str, Any]:
        favorite = self._favorite(payload.get("favorite_id"))
        config = self._normalize_signal_config(payload, favorite)
        signal_set_id = uuid.uuid4().hex
        now = _now_ms()
        name = config.get("name") or f"{favorite['name']} 异动表 {config['start_date']}~{config['end_date']}"
        summary = _initial_signal_summary(config)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_sets (
                    id, favorite_id, name, status, config, favorite_snapshot, summary, error,
                    created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_set_id,
                    favorite["id"],
                    name,
                    "running",
                    _dump_json(config),
                    _dump_json(favorite),
                    _dump_json(summary),
                    "",
                    now,
                    now,
                    None,
                ),
            )

        try:
            self._start_signal_set_job(signal_set_id, favorite, config)
        except Exception as exc:
            self._mark_signal_set_failed(signal_set_id, str(exc))

        item = self.get_signal_set(signal_set_id)
        if item is None:
            raise RuntimeError("异动表记录写入失败")
        return item

    def _start_signal_set_job(
        self,
        signal_set_id: str,
        favorite: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        thread = threading.Thread(
            target=self._run_signal_set_job,
            args=(signal_set_id, favorite, config),
            daemon=True,
            name=f"signal-set-{signal_set_id[:8]}",
        )
        thread.start()

    def _run_signal_set_job(
        self,
        signal_set_id: str,
        favorite: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        try:
            events, summary = self._build_signal_events(signal_set_id, favorite, config)
            with self._connect() as conn:
                conn.execute("DELETE FROM signal_events WHERE signal_set_id = ?", (signal_set_id,))
                conn.executemany(
                    """
                    INSERT INTO signal_events (
                        id, signal_set_id, favorite_id, inst_id, timeframe, date,
                        signal_ts, confirm_ts, signal_time, confirm_time, strength,
                        matched_conditions, metadata_values, row_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            event["id"],
                            event["signal_set_id"],
                            event["favorite_id"],
                            event["inst_id"],
                            event["timeframe"],
                            event["date"],
                            event["signal_ts"],
                            event["confirm_ts"],
                            event["signal_time"],
                            event["confirm_time"],
                            event["strength"],
                            _dump_json(event.get("matched_conditions", [])),
                            _dump_json(event.get("metadata_values", {})),
                            _dump_json(event.get("row_snapshot", {})),
                        )
                        for event in events
                    ],
                )
                conn.execute(
                    """
                    UPDATE signal_sets
                    SET status = ?, summary = ?, error = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    ("completed", _dump_json(summary), "", _now_ms(), signal_set_id),
                )
        except Exception as exc:
            self._mark_signal_set_failed(signal_set_id, str(exc))

    def _mark_signal_set_failed(self, signal_set_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE signal_sets
                SET status = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                ("failed", error, _now_ms(), signal_set_id),
            )

    def list_signal_sets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, favorite_id, name, status, config, favorite_snapshot, summary, error,
                       created_at, started_at, finished_at
                FROM signal_sets
                ORDER BY created_at DESC
                LIMIT 100
                """
            ).fetchall()
        return [self._signal_set_row_to_item(row, compact=True) for row in rows]

    def get_signal_set(self, signal_set_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, favorite_id, name, status, config, favorite_snapshot, summary, error,
                       created_at, started_at, finished_at
                FROM signal_sets
                WHERE id = ?
                """,
                (signal_set_id,),
            ).fetchone()
        return self._signal_set_row_to_item(row, compact=False) if row else None

    def list_events(self, signal_set_id: str, limit: int = SIGNAL_EVENT_LIMIT) -> list[dict[str, Any]]:
        self._require_signal_set(signal_set_id)
        normalized_limit = max(1, min(int(limit or SIGNAL_EVENT_LIMIT), 5000))
        return self._events_for_signal_set(signal_set_id, limit=normalized_limit)

    def create_backtest_from_signal_set(self, payload: dict[str, Any]) -> dict[str, Any]:
        signal_set = self._require_signal_set(str(payload.get("signal_set_id") or ""))
        if signal_set.get("status") != "completed":
            raise ValueError("只能对已完成的异动表做回测")
        config = self._normalize_backtest_config(payload, signal_set)
        events = self._events_for_signal_set(signal_set["id"], limit=None)
        run_id = uuid.uuid4().hex
        now = _now_ms()
        name = config.get("name") or f"{signal_set['name']} 规则回测"

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
                    signal_set["favorite_id"],
                    "running",
                    _dump_json(config),
                    "",
                    "",
                    now,
                    now,
                    None,
                ),
            )

        try:
            result = self._execute_signal_backtest(config, signal_set, events)
            status = "completed"
            error = ""
        except Exception as exc:
            result = None
            status = "failed"
            error = str(exc)

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE backtest_runs
                SET status = ?, result = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    _dump_json(result) if result else "",
                    error,
                    _now_ms(),
                    run_id,
                ),
            )

        item = self._get_backtest_run(run_id)
        if item is None:
            raise RuntimeError("回测运行记录写入失败")
        return item

    def _build_signal_events(
        self,
        signal_set_id: str,
        favorite: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        direct_condition = self._direct_script_current_bar_condition(favorite)
        if direct_condition:
            return self._build_direct_script_signal_events(signal_set_id, favorite, config, direct_condition)

        started = time.perf_counter()
        checkpoints = self._checkpoints(config)
        if not checkpoints:
            raise ValueError("异动扫描区间内没有可用 K 线检查点")

        metadata_filters = _favorite_metadata_filters(favorite)
        script_cache: dict[tuple[str, str, str], dict[str, list[dict[str, str]]]] = {}
        events: list[dict[str, Any]] = []
        total_matched = 0
        total_returned = 0
        total_contracts = 0
        truncated_events = 0
        checkpoint_samples: list[dict[str, Any]] = []

        for index, checkpoint in enumerate(checkpoints, start=1):
            response = query_screener(
                timeframe=config["signal_timeframe"],
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
            rows = response.get("rows", []) or []
            matched_count = int(response.get("matched_count") or len(rows))
            total_matched += matched_count
            total_returned += len(rows)
            total_contracts = max(total_contracts, int(response.get("total_contracts") or 0))
            truncated_events += max(0, matched_count - len(rows))

            if rows or len(checkpoint_samples) < 8:
                checkpoint_samples.append(
                    {
                        "index": index,
                        "date": checkpoint["date"],
                        "as_of_ts": checkpoint["as_of_ts"],
                        "as_of_time": _format_time(checkpoint["as_of_ts"]),
                        "confirm_ts": checkpoint["confirm_ts"],
                        "confirm_time": _format_time(checkpoint["confirm_ts"]),
                        "matched_count": matched_count,
                        "returned_count": len(rows),
                        "duration_ms": int(response.get("duration_ms") or 0),
                    }
                )
                checkpoint_samples = checkpoint_samples[-30:]

            for row in rows:
                inst_id = str(row.get("inst_id") or "")
                if not inst_id:
                    continue
                fallback_signal_ts = _safe_int(row.get("latest_ts")) or checkpoint["as_of_ts"]
                signal_ts, confirm_ts = _event_signal_anchor(
                    row,
                    fallback_signal_ts,
                    config["signal_timeframe"],
                )
                events.append(
                    {
                        "id": uuid.uuid4().hex,
                        "signal_set_id": signal_set_id,
                        "favorite_id": favorite["id"],
                        "inst_id": inst_id,
                        "timeframe": config["signal_timeframe"],
                        "date": checkpoint["date"],
                        "signal_ts": signal_ts,
                        "confirm_ts": confirm_ts,
                        "signal_time": _format_time(signal_ts),
                        "confirm_time": _format_time(confirm_ts),
                        "strength": _event_strength(row),
                        "matched_conditions": row.get("matched_conditions") or [],
                        "metadata_values": row.get("metadata_values") or {},
                        "row_snapshot": row,
                    }
                )

        events.sort(key=lambda item: (int(item["confirm_ts"]), -float(item.get("strength") or 0), str(item["inst_id"])))
        unique_contracts = len({event["inst_id"] for event in events})
        summary = {
            "start_date": config["start_date"],
            "end_date": config["end_date"],
            "signal_timeframe": config["signal_timeframe"],
            "signal_mode": config["signal_mode"],
            "checkpoint_count": len(checkpoints),
            "matched_count": total_matched,
            "returned_count": total_returned,
            "event_count": len(events),
            "truncated_events": truncated_events,
            "unique_contracts": unique_contracts,
            "total_contracts": total_contracts,
            "first_signal_ts": events[0]["signal_ts"] if events else None,
            "first_signal_time": events[0]["signal_time"] if events else None,
            "last_signal_ts": events[-1]["signal_ts"] if events else None,
            "last_signal_time": events[-1]["signal_time"] if events else None,
            "first_confirm_ts": events[0]["confirm_ts"] if events else None,
            "first_confirm_time": events[0]["confirm_time"] if events else None,
            "last_confirm_ts": events[-1]["confirm_ts"] if events else None,
            "last_confirm_time": events[-1]["confirm_time"] if events else None,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "checkpoint_samples": checkpoint_samples,
        }
        return events, summary

    def _build_direct_script_signal_events(
        self,
        signal_set_id: str,
        favorite: dict[str, Any],
        config: dict[str, Any],
        condition: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        started = time.perf_counter()
        indicator = condition["_indicator"]
        indicator_id = str(indicator["id"])
        signal_timeframe = config["signal_timeframe"]
        period_ms = _period_ms(signal_timeframe)
        dates = [item for item in _available_dates(signal_timeframe) if config["start_date"] <= item <= config["end_date"]]
        if not dates:
            raise ValueError("异动扫描区间内没有可用 K 线日期")

        events: list[dict[str, Any]] = []
        checkpoint_count = 0
        checkpoint_samples: list[dict[str, Any]] = []
        for date_index, item_date in enumerate(dates, start=1):
            bars = self._sample_bars(signal_timeframe, item_date)
            checkpoint_count += len(bars) if config["signal_mode"] == "each_bar_close" else min(1, len(bars))
            result = script_indicator_service.trial_run(
                indicator_id,
                date=item_date,
                input_timeframe=signal_timeframe,
                limit=1000,
            )
            if result.get("timed_out"):
                detail = result.get("stderr") or "脚本指标运行超时"
                raise TimeoutError(f"{indicator.get('name_zh') or indicator_id}：{detail}")
            if not result.get("success"):
                detail = result.get("stderr") or "脚本执行失败，无法生成异动表"
                raise ValueError(f"{indicator.get('name_zh') or indicator_id}：{detail}")

            rows = result.get("rows", []) or []
            if config["signal_mode"] == "daily" and rows:
                latest_by_inst: dict[str, dict[str, str]] = {}
                for row in rows:
                    inst_id = str(row.get("inst_id") or "")
                    if not inst_id:
                        continue
                    current_ts = _safe_int(row.get("ts")) or -1
                    previous_ts = _safe_int(latest_by_inst.get(inst_id, {}).get("ts")) if inst_id in latest_by_inst else None
                    if previous_ts is None or current_ts >= previous_ts:
                        latest_by_inst[inst_id] = row
                rows = list(latest_by_inst.values())

            if rows or len(checkpoint_samples) < 8:
                checkpoint_samples.append(
                    {
                        "index": date_index,
                        "date": item_date,
                        "as_of_ts": _safe_int(rows[-1].get("ts")) if rows else (bars[-1].ts if bars else None),
                        "as_of_time": _format_time(_safe_int(rows[-1].get("ts")) if rows else (bars[-1].ts if bars else None)),
                        "confirm_ts": (_safe_int(rows[-1].get("ts")) + period_ms) if rows and _safe_int(rows[-1].get("ts")) else None,
                        "confirm_time": _format_time((_safe_int(rows[-1].get("ts")) + period_ms) if rows and _safe_int(rows[-1].get("ts")) else None),
                        "matched_count": len(rows),
                        "returned_count": len(rows),
                        "duration_ms": int(result.get("elapsed_ms") or 0),
                    }
                )
                checkpoint_samples = checkpoint_samples[-30:]

            for row in rows:
                inst_id = str(row.get("inst_id") or "")
                signal_ts = _safe_int(row.get("ts"))
                if not inst_id or signal_ts is None:
                    continue
                value = str(row.get("value") or "")
                strength = _safe_float(value) or 0.0
                events.append(
                    {
                        "id": uuid.uuid4().hex,
                        "signal_set_id": signal_set_id,
                        "favorite_id": favorite["id"],
                        "inst_id": inst_id,
                        "timeframe": signal_timeframe,
                        "date": item_date,
                        "signal_ts": signal_ts,
                        "confirm_ts": signal_ts + period_ms,
                        "signal_time": _format_time(signal_ts),
                        "confirm_time": _format_time(signal_ts + period_ms),
                        "strength": _round(strength, 6),
                        "matched_conditions": [_metadata_script_reason(indicator, condition)],
                        "metadata_values": {
                            indicator_id: value,
                            f"{indicator_id}::ts": str(signal_ts),
                        },
                        "row_snapshot": {
                            "inst_id": inst_id,
                            "latest_ts": signal_ts,
                            "latest_time": _format_time(signal_ts),
                            "metadata_values": {
                                indicator_id: value,
                                f"{indicator_id}::ts": str(signal_ts),
                            },
                            "matched_conditions": [_metadata_script_reason(indicator, condition)],
                        },
                    }
                )

        events.sort(key=lambda item: (int(item["confirm_ts"]), -float(item.get("strength") or 0), str(item["inst_id"])))
        unique_contracts = len({event["inst_id"] for event in events})
        summary = {
            "start_date": config["start_date"],
            "end_date": config["end_date"],
            "signal_timeframe": signal_timeframe,
            "signal_mode": config["signal_mode"],
            "checkpoint_count": checkpoint_count,
            "matched_count": len(events),
            "returned_count": len(events),
            "event_count": len(events),
            "truncated_events": 0,
            "unique_contracts": unique_contracts,
            "total_contracts": max((len(data_source_service.contract_files(signal_timeframe, item)) for item in dates), default=0),
            "first_signal_ts": events[0]["signal_ts"] if events else None,
            "first_signal_time": events[0]["signal_time"] if events else None,
            "last_signal_ts": events[-1]["signal_ts"] if events else None,
            "last_signal_time": events[-1]["signal_time"] if events else None,
            "first_confirm_ts": events[0]["confirm_ts"] if events else None,
            "first_confirm_time": events[0]["confirm_time"] if events else None,
            "last_confirm_ts": events[-1]["confirm_ts"] if events else None,
            "last_confirm_time": events[-1]["confirm_time"] if events else None,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "checkpoint_samples": checkpoint_samples,
            "direct_script": True,
            "indicator_id": indicator_id,
        }
        return events, summary

    def _execute_signal_backtest(
        self,
        config: dict[str, Any],
        signal_set: dict[str, Any],
        events: list[dict[str, Any]],
        initial_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        entry_timeframe = config["entry_timeframe"]
        trade_dates = self._trade_dates(
            entry_timeframe,
            signal_set["config"]["start_date"],
            signal_set["config"]["end_date"],
            int(config["exit_hold_minutes"]),
            int(config["entry_window_minutes"]),
        )
        if events and not trade_dates:
            raise ValueError("回测区间内没有可用成交 K 线")

        price_cache: dict[tuple[str, str], PriceSeries] = {}
        entry_candidates: list[EntryCandidate] = []
        counters = {
            "checkpoints": int((signal_set.get("summary") or {}).get("checkpoint_count") or 0),
            "matched_signals": len(events),
            "opened_trades": 0,
            "skipped_overlap": 0,
            "skipped_max_positions": 0,
            "skipped_insufficient_equity": 0,
            "skipped_account_depleted": 0,
            "skipped_no_entry": 0,
            "skipped_no_exit": 0,
            "skipped_entry_rule": 0,
        }

        for event in events:
            inst_id = str(event.get("inst_id") or "")
            if not inst_id:
                continue
            series = price_cache.get((entry_timeframe, inst_id))
            if series is None:
                series = self._price_series(entry_timeframe, inst_id, trade_dates)
                price_cache[(entry_timeframe, inst_id)] = series
            candidate = self._entry_candidate(event, series, config)
            if candidate is None:
                counters["skipped_no_entry"] += 1
                counters["skipped_entry_rule"] += 1
                continue
            entry_candidates.append(candidate)

        entry_candidates.sort(
            key=lambda item: (
                int(item.entry_bar.ts),
                -float(item.event.get("strength") or 0),
                str(item.event.get("inst_id") or ""),
            )
        )

        initial_state = initial_state if isinstance(initial_state, dict) else {}
        initial_positions = initial_state.get("open_positions") if isinstance(initial_state.get("open_positions"), list) else []
        open_positions: list[dict[str, Any]] = [
            {
                "inst_id": str(item.get("inst_id") or ""),
                "exit_ts": int(item.get("exit_ts") or 0),
                "pnl_usdt": float(item.get("pnl_usdt") or 0),
            }
            for item in initial_positions
            if isinstance(item, dict) and item.get("inst_id") and item.get("exit_ts")
        ]
        trades: list[dict[str, Any]] = []
        opened_by_confirm: dict[int, int] = {}
        position_usdt = float(config["position_usdt"])
        initial_capital = position_usdt * int(config["max_positions"])
        realized_pnl = float(initial_state.get("realized_pnl") or 0)

        for candidate in entry_candidates:
            inst_id = str(candidate.event.get("inst_id") or "")
            entry_ts = candidate.entry_bar.ts
            still_open: list[dict[str, Any]] = []
            for item in open_positions:
                if int(item["exit_ts"]) <= entry_ts:
                    realized_pnl += float(item.get("pnl_usdt") or 0)
                else:
                    still_open.append(item)
            open_positions = still_open
            open_symbols = {str(item["inst_id"]) for item in open_positions}
            if inst_id in open_symbols:
                counters["skipped_overlap"] += 1
                continue
            if len(open_positions) >= int(config["max_positions"]):
                counters["skipped_max_positions"] += 1
                continue
            equity_at_entry = initial_capital + realized_pnl
            if equity_at_entry <= 0:
                counters["skipped_account_depleted"] += 1
                continue
            locked_margin = len(open_positions) * position_usdt
            if equity_at_entry - locked_margin + 1e-9 < position_usdt:
                counters["skipped_insufficient_equity"] += 1
                continue

            series = price_cache[(entry_timeframe, inst_id)]
            trade, skip_reason = self._simulate_trade(len(trades) + 1, candidate, series, config)
            if trade is None:
                if skip_reason == "no_exit":
                    counters["skipped_no_exit"] += 1
                else:
                    counters["skipped_no_entry"] += 1
                continue
            trades.append(trade)
            open_positions.append({"inst_id": inst_id, "exit_ts": trade["exit_ts"], "pnl_usdt": trade["pnl_usdt"]})
            counters["opened_trades"] += 1
            opened_by_confirm[int(candidate.event["confirm_ts"])] = opened_by_confirm.get(int(candidate.event["confirm_ts"]), 0) + 1

        checkpoints = self._backtest_checkpoints(events, opened_by_confirm)
        summary, equity, daily_equity = self._summarize(config, signal_set, counters, trades)
        summary["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return {
            "summary": summary,
            "equity": equity,
            "daily_equity": daily_equity,
            "trades": trades,
            "checkpoints": checkpoints,
            "favorite": signal_set.get("favorite"),
            "signal_set": {
                "id": signal_set["id"],
                "name": signal_set["name"],
                "summary": signal_set.get("summary") or {},
            },
        }

    def _entry_candidate(
        self,
        event: dict[str, Any],
        series: PriceSeries,
        config: dict[str, Any],
    ) -> EntryCandidate | None:
        if not series.bars:
            return None
        confirm_ts = int(event["confirm_ts"])
        window_ms = int(config["entry_window_minutes"]) * MINUTE_MS
        entry_rule = str(config["entry_rule"])
        period_ms = _period_ms(config["entry_timeframe"])

        if entry_rule == "next_bar_open":
            entry_bar = _bar_at_or_after(series, confirm_ts)
            if entry_bar is None or entry_bar.ts > confirm_ts + max(window_ms, period_ms):
                return None
            return EntryCandidate(
                event=event,
                entry_bar=entry_bar,
                trigger_pct=[],
                delay_min=_round((entry_bar.ts - confirm_ts) / MINUTE_MS, 4),
                entry_reason="异动确认后下一根K线开盘",
            )

        if entry_rule != "consecutive_green_bars":
            raise ValueError(f"不支持的入场规则：{entry_rule}")

        start_index = bisect_left(series.timestamps, confirm_ts)
        consecutive = int(config["entry_consecutive_bars"])
        min_gain = float(config["entry_min_gain_pct_each"])
        max_offsets = max(1, math.ceil(window_ms / period_ms))
        if config["entry_timeframe"] == "5m" and int(config["entry_window_minutes"]) == 60:
            max_offsets = min(max_offsets, BOT_LIKE_MAX_ENTRY_BARS)

        max_offset = min(max_offsets, max(0, len(series.bars) - start_index - consecutive))
        for offset in range(max_offset):
            trigger: list[float] = []
            matched = True
            for step in range(consecutive):
                bar = series.bars[start_index + offset + step]
                if bar.open <= 0 or bar.close <= bar.open:
                    matched = False
                    break
                gain = (bar.close - bar.open) / bar.open * 100
                if gain < min_gain:
                    matched = False
                    break
                trigger.append(_round(gain, 4))
            if not matched:
                continue

            entry_index = start_index + offset + consecutive
            if entry_index >= len(series.bars):
                return None
            entry_bar = series.bars[entry_index]
            if entry_bar.ts > confirm_ts + window_ms:
                continue
            return EntryCandidate(
                event=event,
                entry_bar=entry_bar,
                trigger_pct=trigger,
                delay_min=_round((entry_bar.ts - confirm_ts) / MINUTE_MS, 4),
                entry_reason=f"连续{consecutive}根阳线且单根涨幅>={min_gain:g}%后下一根开盘",
            )
        return None

    def _simulate_trade(
        self,
        run_index: int,
        candidate: EntryCandidate,
        series: PriceSeries,
        config: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        entry_idx = bisect_left(series.timestamps, candidate.entry_bar.ts)
        if entry_idx >= len(series.bars):
            return None, "no_entry"
        target_ts = candidate.entry_bar.ts + int(config["exit_hold_minutes"]) * MINUTE_MS
        exit_idx = bisect_left(series.timestamps, target_ts)
        if exit_idx >= len(series.bars) or exit_idx <= entry_idx:
            return None, "no_exit"

        side = str(config["side"])
        raw_entry = float(candidate.entry_bar.open)
        raw_exit = float(series.bars[exit_idx].open)
        real_exit_idx = exit_idx
        exit_reason = "到期平仓"
        stop_loss_pct = float(config["stop_loss_pct"])
        stop_model = str(config["stop_model"])
        position_usdt = float(config["position_usdt"])
        leverage = float(config["leverage"])
        notional_usdt = position_usdt * leverage
        liquidation_price = _liquidation_price(side, raw_entry, leverage)
        liquidation_pct = 100 / leverage if leverage > 0 else None
        liquidated = False
        max_adverse = 0.0
        max_favorable = 0.0

        if raw_entry <= 0:
            return None, "no_entry"
        if side == "short":
            stop_price = raw_entry * (1 + stop_loss_pct / 100)
        else:
            stop_price = raw_entry * (1 - stop_loss_pct / 100)

        def stop_hit(bar: PriceBar, *, checkpoint: bool) -> bool:
            if stop_model == "hard_stop_intrabar":
                return bar.high >= stop_price if side == "short" else bar.low <= stop_price
            if stop_model == "bot_like_checkpoint":
                return checkpoint and (bar.open >= stop_price if side == "short" else bar.open <= stop_price)
            raise ValueError(f"不支持的止损模型：{stop_model}")

        stop_before_liquidation = (
            stop_model == "hard_stop_intrabar"
            and liquidation_pct is not None
            and stop_loss_pct <= liquidation_pct
        )

        for index in range(entry_idx, exit_idx):
            bar = series.bars[index]
            adverse, favorable = _excursion_pct(side, raw_entry, bar)
            max_adverse = max(max_adverse, adverse)
            max_favorable = max(max_favorable, favorable)

            if stop_before_liquidation and stop_hit(bar, checkpoint=index > entry_idx):
                real_exit_idx = index
                raw_exit = stop_price
                exit_reason = "盘中硬止损"
                break

            if liquidation_price is not None and _liquidation_hit(side, liquidation_price, bar):
                real_exit_idx = index
                raw_exit = liquidation_price
                exit_reason = "爆仓"
                liquidated = True
                break

            if not stop_before_liquidation and stop_hit(bar, checkpoint=index > entry_idx):
                real_exit_idx = index
                raw_exit = stop_price if stop_model == "hard_stop_intrabar" else float(bar.open)
                exit_reason = "盘中硬止损" if stop_model == "hard_stop_intrabar" else "检查点止损"
                break

        exit_bar = series.bars[real_exit_idx]
        adverse, favorable = _excursion_pct(side, raw_entry, exit_bar)
        max_adverse = max(max_adverse, adverse)
        max_favorable = max(max_favorable, favorable)

        fee_bps = float(config["fee_bps_per_side"])
        slippage_bps = float(config["slippage_bps_per_side"])
        if side == "short":
            gross_pct = -((raw_exit - raw_entry) / raw_entry) * 100
        else:
            gross_pct = (raw_exit - raw_entry) / raw_entry * 100
        fee_pct = 2 * fee_bps / 100
        slippage_pct = 2 * slippage_bps / 100
        net_pct_on_notional = gross_pct - fee_pct - slippage_pct
        fee_usdt = notional_usdt * fee_pct / 100
        slippage_usdt = notional_usdt * slippage_pct / 100
        pnl_usdt = -position_usdt if liquidated else notional_usdt * net_pct_on_notional / 100
        net_return_pct = pnl_usdt / position_usdt * 100 if position_usdt else 0
        event = candidate.event

        return (
            {
                "id": run_index,
                "inst_id": event.get("inst_id"),
                "side": side,
                "direction": "做空" if side == "short" else "做多",
                "signal_set_event_id": event.get("id"),
                "signal_date": event.get("date"),
                "signal_ts": event.get("signal_ts"),
                "signal_time": event.get("signal_time"),
                "confirm_ts": event.get("confirm_ts"),
                "confirm_time": event.get("confirm_time"),
                "entry_ts": candidate.entry_bar.ts,
                "entry_time": _format_time(candidate.entry_bar.ts),
                "exit_ts": exit_bar.ts,
                "exit_time": _format_time(exit_bar.ts),
                "hold_hours": _round(int(config["exit_hold_minutes"]) / 60, 4),
                "exit_hold_minutes": int(config["exit_hold_minutes"]),
                "position_usdt": _round(position_usdt, 4),
                "leverage": _round(leverage, 4),
                "notional_usdt": _round(notional_usdt, 4),
                "raw_entry_price": _round(raw_entry, 12),
                "raw_exit_price": _round(raw_exit, 12),
                "entry_price": _round(raw_entry, 12),
                "exit_price": _round(raw_exit, 12),
                "stop_price": _round(stop_price, 12),
                "liquidation_price": _round(liquidation_price, 12) if liquidation_price is not None else None,
                "liquidated": liquidated,
                "exit_reason": exit_reason,
                "entry_reason": candidate.entry_reason,
                "trigger_pct": candidate.trigger_pct,
                "delay_min": candidate.delay_min,
                "gross_return_pct": _round(gross_pct * leverage, 4),
                "net_return_pct": _round(net_return_pct, 4),
                "price_return_pct": _round(gross_pct, 4),
                "fee_usdt": _round(fee_usdt, 4),
                "slippage_usdt": _round(slippage_usdt, 4),
                "cost_usdt": _round(fee_usdt + slippage_usdt, 4),
                "pnl_usdt": _round(pnl_usdt, 4),
                "max_adverse_pct": _round(max_adverse, 4),
                "max_favorable_pct": _round(max_favorable, 4),
                "matched_conditions": event.get("matched_conditions", []),
                "signal_metrics": _signal_metrics(event),
            },
            "",
        )

    def _summarize(
        self,
        config: dict[str, Any],
        signal_set: dict[str, Any],
        counters: dict[str, int],
        trades: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        sorted_trades = sorted(trades, key=lambda item: (int(item["exit_ts"]), int(item["id"])))
        initial_capital = float(config["position_usdt"]) * int(config["max_positions"])
        equity_value = initial_capital
        peak = initial_capital
        max_drawdown_pct = 0.0
        first_ts = int((signal_set.get("summary") or {}).get("first_confirm_ts") or 0) or None
        equity = [
            {
                "ts": first_ts,
                "time": _format_time(first_ts) if first_ts else None,
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
            "start_date": signal_set["config"].get("start_date"),
            "end_date": signal_set["config"].get("end_date"),
            "signal_mode": signal_set["config"].get("signal_mode"),
            "signal_timeframe": signal_set["config"].get("signal_timeframe"),
            "entry_timeframe": config["entry_timeframe"],
            "entry_rule": config["entry_rule"],
            "side": config["side"],
            "hold_hours": _round(int(config["exit_hold_minutes"]) / 60, 4),
            "exit_hold_minutes": int(config["exit_hold_minutes"]),
            "stop_loss_pct": config["stop_loss_pct"],
            "stop_model": config["stop_model"],
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
            "position_usdt": config["position_usdt"],
            "leverage": config["leverage"],
            "max_positions": config["max_positions"],
            "fee_bps_per_side": config["fee_bps_per_side"],
            "slippage_bps_per_side": config["slippage_bps_per_side"],
        }
        daily_equity = self._daily_equity_curve(
            initial_capital=initial_capital,
            sorted_trades=sorted_trades,
            start_date=str(signal_set["config"].get("start_date") or ""),
            end_date=str(signal_set["config"].get("end_date") or ""),
        )
        return summary, equity, daily_equity

    def _daily_equity_curve(
        self,
        *,
        initial_capital: float,
        sorted_trades: list[dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        try:
            cursor = Date.fromisoformat(start_date)
            end = Date.fromisoformat(end_date)
        except ValueError:
            return []

        pnl_by_date: dict[Date, float] = {}
        for trade in sorted_trades:
            exit_date_text = str(trade.get("exit_time") or "")[:10]
            try:
                exit_date = Date.fromisoformat(exit_date_text)
            except ValueError:
                continue
            pnl_by_date[exit_date] = pnl_by_date.get(exit_date, 0.0) + float(trade.get("pnl_usdt") or 0)
            if exit_date > end:
                end = exit_date

        total_pnl = 0.0
        peak = initial_capital
        points: list[dict[str, Any]] = []
        while cursor <= end:
            total_pnl += pnl_by_date.get(cursor, 0.0)
            equity_value = initial_capital + total_pnl
            peak = max(peak, equity_value)
            drawdown_pct = (equity_value / peak - 1) * 100 if peak else 0.0
            points.append(
                {
                    "ts": None,
                    "time": cursor.isoformat(),
                    "equity": _round(equity_value, 4),
                    "pnl_usdt": _round(total_pnl, 4),
                    "drawdown_pct": _round(drawdown_pct, 4),
                }
            )
            cursor += timedelta(days=1)
        return points

    def _backtest_checkpoints(self, events: list[dict[str, Any]], opened_by_confirm: dict[int, int]) -> list[dict[str, Any]]:
        grouped: dict[int, dict[str, Any]] = {}
        for event in events:
            confirm_ts = int(event["confirm_ts"])
            item = grouped.setdefault(
                confirm_ts,
                {
                    "index": 0,
                    "date": event.get("date"),
                    "as_of_ts": event.get("signal_ts"),
                    "as_of_time": event.get("signal_time"),
                    "signal_ts": confirm_ts,
                    "signal_time": event.get("confirm_time"),
                    "matched_count": 0,
                    "opened_count": 0,
                    "duration_ms": 0,
                },
            )
            item["matched_count"] += 1
        items = [grouped[key] for key in sorted(grouped)]
        for index, item in enumerate(items, start=1):
            item["index"] = index
            item["opened_count"] = opened_by_confirm.get(int(item["signal_ts"]), 0)
        return items[-100:]

    def _checkpoints(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        signal_timeframe = config["signal_timeframe"]
        period_ms = _period_ms(signal_timeframe)
        dates = [item for item in _available_dates(signal_timeframe) if config["start_date"] <= item <= config["end_date"]]
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
                        "confirm_ts": bar.ts + period_ms,
                    }
                )
        checkpoints.sort(key=lambda item: (item["confirm_ts"], item["date"]))
        checkpoint_limit = int(config.get("checkpoint_limit") or MAX_CHECKPOINTS)
        if len(checkpoints) > checkpoint_limit:
            raise ValueError(
                f"异动扫描检查点过多：{len(checkpoints)} 个，当前上限 {checkpoint_limit}；请缩短日期区间。"
            )
        return checkpoints

    def _sample_bars(self, timeframe: str, item_date: str) -> list[PriceBar]:
        files = data_source_service.contract_files(timeframe, item_date)
        if not files:
            return []
        preferred_names = ("BTC-USDT-SWAP.csv.gz", "ETH-USDT-SWAP.csv.gz")
        path = next((item for item in files if item.name in preferred_names), files[0])
        return _read_price_bars(path)

    def _trade_dates(
        self,
        timeframe: str,
        start_date: str,
        end_date: str,
        hold_minutes: int,
        entry_window_minutes: int,
    ) -> list[str]:
        buffer_days = math.ceil((hold_minutes + entry_window_minutes) / (24 * 60)) + 3
        end_buffer = Date.fromisoformat(end_date) + timedelta(days=buffer_days)
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
            raise ValueError("请选择收藏条件")
        favorite = screener_favorite_repository.get(normalized)
        if not favorite:
            raise KeyError(f"收藏条件不存在：{normalized}")
        return favorite

    def _direct_script_current_bar_condition(self, favorite: dict[str, Any]) -> dict[str, Any] | None:
        if any(favorite.get(key) not in (None, "") for key in ("min_ret_15m", "min_vol_ratio_60", "min_vol_quote_15m")):
            return None
        conditions = [item for item in favorite.get("metadata_conditions") or [] if isinstance(item, dict)]
        if len(conditions) != 1:
            return None
        condition = conditions[0]
        if not condition.get("match_current_bar"):
            return None
        indicator_id = str(condition.get("indicator_id") or (condition.get("indicator") or {}).get("id") or "")
        indicator = indicator_repository.get(indicator_id)
        if not indicator or indicator.get("source_type") != "script":
            return None
        operator = str(condition.get("operator") or "any_not_empty")
        if operator not in {"any_not_empty", "not_empty", "is_not_empty", "not_blank", "不为空"}:
            return None
        return {**condition, "_indicator": indicator}

    def _require_signal_set(self, signal_set_id: str) -> dict[str, Any]:
        normalized = str(signal_set_id or "").strip()
        if not normalized:
            raise ValueError("请选择异动表")
        item = self.get_signal_set(normalized)
        if item is None:
            raise KeyError(f"异动表不存在：{normalized}")
        return item

    def _normalize_signal_config(self, payload: dict[str, Any], favorite: dict[str, Any]) -> dict[str, Any]:
        start_date = _validate_date(str(payload.get("start_date") or ""), "开始日期")
        end_date = _validate_date(str(payload.get("end_date") or ""), "结束日期")
        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        signal_mode = str(payload.get("signal_mode") or "each_bar_close")
        if signal_mode == "hourly":
            signal_mode = "each_bar_close"
        if signal_mode not in {"daily", "each_bar_close"}:
            raise ValueError("异动扫描频率只支持 daily 或 each_bar_close")
        signal_timeframe = _normalize_timeframe(str(payload.get("signal_timeframe") or favorite.get("timeframe") or "1H"))
        if signal_mode == "each_bar_close" and _period_ms(signal_timeframe) >= 24 * 60 * 60 * 1000:
            raise ValueError("逐根K线扫描不支持日线周期，请选择 1H/5m/1m")
        return {
            "favorite_id": favorite["id"],
            "favorite_name": favorite["name"],
            "name": str(payload.get("name") or "").strip(),
            "start_date": start_date,
            "end_date": end_date,
            "signal_timeframe": signal_timeframe,
            "signal_mode": signal_mode,
            "checkpoint_limit": _bounded_int(payload.get("checkpoint_limit"), MAX_CHECKPOINTS, 1, 5000, "检查点上限"),
        }

    def _normalize_backtest_config(self, payload: dict[str, Any], signal_set: dict[str, Any]) -> dict[str, Any]:
        side = str(payload.get("side") or "short").lower()
        if side not in {"long", "short"}:
            raise ValueError("入场方向只支持 long 或 short")
        entry_rule = str(payload.get("entry_rule") or "consecutive_green_bars")
        if entry_rule not in {"next_bar_open", "consecutive_green_bars"}:
            raise ValueError("入场规则只支持 next_bar_open 或 consecutive_green_bars")
        stop_model = str(payload.get("stop_model") or "bot_like_checkpoint")
        if stop_model not in {"bot_like_checkpoint", "hard_stop_intrabar"}:
            raise ValueError("止损模型只支持 bot_like_checkpoint 或 hard_stop_intrabar")
        entry_timeframe = _normalize_timeframe(str(payload.get("entry_timeframe") or "5m"))
        exit_hold_minutes = _bounded_int(payload.get("exit_hold_minutes"), 440, 1, 60 * 24 * 30, "持仓分钟")
        return {
            "signal_set_id": signal_set["id"],
            "favorite_id": signal_set["favorite_id"],
            "favorite_name": (signal_set.get("favorite") or {}).get("name", ""),
            "name": str(payload.get("name") or "").strip(),
            "side": side,
            "entry_timeframe": entry_timeframe,
            "entry_rule": entry_rule,
            "entry_window_minutes": _bounded_int(payload.get("entry_window_minutes"), 60, 1, 24 * 60, "入场窗口分钟"),
            "entry_consecutive_bars": _bounded_int(payload.get("entry_consecutive_bars"), 2, 1, 20, "连续K线根数"),
            "entry_min_gain_pct_each": _bounded_float(payload.get("entry_min_gain_pct_each"), 2.0, 0.0, 1000.0, "单根涨幅阈值"),
            "exit_hold_minutes": exit_hold_minutes,
            "hold_hours": _round(exit_hold_minutes / 60, 4),
            "stop_loss_pct": _bounded_float(payload.get("stop_loss_pct"), 15.0, 0.0, 1000.0, "止损百分比"),
            "stop_model": stop_model,
            "position_usdt": _bounded_float(payload.get("position_usdt"), 500.0, 1.0, 1_000_000.0, "单笔保证金"),
            "leverage": _bounded_float(payload.get("leverage"), 1.0, 0.01, 125.0, "杠杆"),
            "max_positions": _bounded_int(payload.get("max_positions"), 2, 1, 100, "最大持仓数"),
            "fee_bps_per_side": _bounded_float(payload.get("fee_bps_per_side"), 5.0, 0.0, 1000.0, "单边手续费bps"),
            "slippage_bps_per_side": _bounded_float(payload.get("slippage_bps_per_side"), 5.0, 0.0, 1000.0, "单边滑点bps"),
        }

    def _events_for_signal_set(self, signal_set_id: str, limit: int | None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, signal_set_id, favorite_id, inst_id, timeframe, date,
                   signal_ts, confirm_ts, signal_time, confirm_time, strength,
                   matched_conditions, metadata_values, row_snapshot
            FROM signal_events
            WHERE signal_set_id = ?
            ORDER BY confirm_ts ASC, strength DESC, inst_id ASC
        """
        params: tuple[Any, ...]
        if limit is not None:
            sql += " LIMIT ?"
            params = (signal_set_id, limit)
        else:
            params = (signal_set_id,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._event_row_to_item(row) for row in rows]

    def _get_backtest_run(self, run_id: str) -> dict[str, Any] | None:
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
        if not row:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "favorite_id": row["favorite_id"],
            "status": row["status"],
            "config": _loads_json(row["config"], {}),
            "result": _loads_json(row["result"], None) if row["result"] else None,
            "error": row["error"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    def _signal_set_row_to_item(self, row: sqlite3.Row, *, compact: bool) -> dict[str, Any]:
        config = _loads_json(row["config"], {})
        favorite = _loads_json(row["favorite_snapshot"], {})
        summary = _loads_json(row["summary"], {}) if row["summary"] else {}
        if compact and summary:
            summary = {key: value for key, value in summary.items() if key != "checkpoint_samples"}
        return {
            "id": row["id"],
            "favorite_id": row["favorite_id"],
            "name": row["name"],
            "status": row["status"],
            "config": config,
            "favorite": {
                "id": favorite.get("id", row["favorite_id"]),
                "name": favorite.get("name", ""),
                "timeframe": favorite.get("timeframe", config.get("signal_timeframe")),
                "condition_count": favorite.get("condition_count", len(favorite.get("metadata_conditions") or [])),
            },
            "summary": summary,
            "error": row["error"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    def _event_row_to_item(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "signal_set_id": row["signal_set_id"],
            "favorite_id": row["favorite_id"],
            "inst_id": row["inst_id"],
            "timeframe": row["timeframe"],
            "date": row["date"],
            "signal_ts": row["signal_ts"],
            "confirm_ts": row["confirm_ts"],
            "signal_time": row["signal_time"],
            "confirm_time": row["confirm_time"],
            "strength": row["strength"],
            "matched_conditions": _loads_json(row["matched_conditions"], []),
            "metadata_values": _loads_json(row["metadata_values"], {}),
            "row_snapshot": _loads_json(row["row_snapshot"], {}),
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_sets (
                    id TEXT PRIMARY KEY,
                    favorite_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config TEXT NOT NULL,
                    favorite_snapshot TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    started_at INTEGER,
                    finished_at INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signal_sets_created_at
                ON signal_sets(created_at DESC)
                """
            )
            conn.execute(
                """
                UPDATE signal_sets
                SET status = ?, error = ?, finished_at = ?
                WHERE status = ?
                """,
                ("failed", "后端服务重启，原后台任务已中断，请重新生成异动表。", _now_ms(), "running"),
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_events (
                    id TEXT PRIMARY KEY,
                    signal_set_id TEXT NOT NULL,
                    favorite_id TEXT NOT NULL,
                    inst_id TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    date TEXT NOT NULL,
                    signal_ts INTEGER NOT NULL,
                    confirm_ts INTEGER NOT NULL,
                    signal_time TEXT,
                    confirm_time TEXT,
                    strength REAL,
                    matched_conditions TEXT NOT NULL,
                    metadata_values TEXT NOT NULL,
                    row_snapshot TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signal_events_set_time
                ON signal_events(signal_set_id, confirm_ts, strength DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signal_events_inst_time
                ON signal_events(inst_id, confirm_ts)
                """
            )
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


def _event_signal_anchor(row: dict[str, Any], fallback_ts: int, fallback_timeframe: str) -> tuple[int, int]:
    metadata_values = row.get("metadata_values") or {}
    anchors: list[tuple[int, int]] = []
    if isinstance(metadata_values, dict):
        for key, value in metadata_values.items():
            if not str(key).endswith("::ts"):
                continue
            ts = _safe_int(value)
            if ts is None:
                continue
            indicator_id = str(key).removesuffix("::ts")
            indicator = indicator_repository.get(indicator_id) or {}
            period_text = str(indicator.get("storage_period") or fallback_timeframe)
            try:
                period_ms = _period_ms(period_text)
            except ValueError:
                period_ms = _period_ms(fallback_timeframe)
            anchors.append((ts, period_ms))
    if not anchors:
        return fallback_ts, fallback_ts + _period_ms(fallback_timeframe)
    signal_ts, period_ms = max(anchors, key=lambda item: item[0])
    return signal_ts, signal_ts + period_ms


def _event_strength(row: dict[str, Any]) -> float:
    pct_candidates: list[float] = []
    other_metadata_candidates: list[float] = []
    metadata_values = row.get("metadata_values") or {}
    if isinstance(metadata_values, dict):
        for key, value in metadata_values.items():
            if str(key).endswith("::ts"):
                continue
            parsed = _safe_float(value)
            if parsed is None:
                continue
            indicator_id = str(key).split("::", 1)[0]
            indicator = indicator_repository.get(indicator_id) or {}
            if indicator.get("unit") == "%":
                pct_candidates.append(parsed)
            else:
                other_metadata_candidates.append(parsed)
    if pct_candidates:
        return _round(max(pct_candidates), 6)

    metric_candidates: list[float] = []
    for key in ("ret_1h", "ret_15m", "amp_15m"):
        value = _safe_float(row.get(key))
        if value is not None:
            metric_candidates.append(value)
    if metric_candidates:
        return _round(max(metric_candidates), 6)
    if other_metadata_candidates:
        return _round(max(other_metadata_candidates), 6)

    latest_close = _safe_float(row.get("latest_close"))
    return _round(latest_close or 0.0, 6)


def _signal_metrics(event: dict[str, Any]) -> dict[str, Any]:
    row = event.get("row_snapshot") or {}
    return {
        "latest_close": row.get("latest_close"),
        "ret_15m": row.get("ret_15m"),
        "ret_1h": row.get("ret_1h"),
        "vol_quote_15m": row.get("vol_quote_15m"),
        "vol_ratio_60": row.get("vol_ratio_60"),
        "strength": event.get("strength"),
        "metadata_values": event.get("metadata_values") or {},
    }


def _metadata_script_reason(indicator: dict[str, Any], condition: dict[str, Any]) -> str:
    name = indicator.get("name_zh") or indicator.get("id") or "脚本指标"
    operator = str(condition.get("operator") or "any_not_empty")
    label = "不为空" if operator in {"any_not_empty", "not_empty", "is_not_empty", "not_blank", "不为空"} else operator
    return f"{name} {label}"


def _excursion_pct(side: str, entry_price: float, bar: PriceBar) -> tuple[float, float]:
    if entry_price <= 0:
        return 0.0, 0.0
    if side == "short":
        adverse = (bar.high - entry_price) / entry_price * 100
        favorable = -(bar.low - entry_price) / entry_price * 100
    else:
        adverse = -(bar.low - entry_price) / entry_price * 100
        favorable = (bar.high - entry_price) / entry_price * 100
    return max(0.0, adverse), max(0.0, favorable)


def _liquidation_price(side: str, entry_price: float, leverage: float) -> float | None:
    if entry_price <= 0 or leverage <= 0:
        return None
    liquidation_move = 1 / leverage
    if side == "short":
        return entry_price * (1 + liquidation_move)
    price = entry_price * (1 - liquidation_move)
    return price if price > 0 else None


def _liquidation_hit(side: str, liquidation_price: float, bar: PriceBar) -> bool:
    if side == "short":
        return bar.high >= liquidation_price
    return bar.low <= liquidation_price


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _initial_signal_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "start_date": config.get("start_date"),
        "end_date": config.get("end_date"),
        "signal_timeframe": config.get("signal_timeframe"),
        "signal_mode": config.get("signal_mode"),
        "checkpoint_count": 0,
        "matched_count": 0,
        "returned_count": 0,
        "event_count": 0,
        "truncated_events": 0,
        "unique_contracts": 0,
        "total_contracts": 0,
        "duration_ms": 0,
    }


signal_pool_service = SignalPoolService()
