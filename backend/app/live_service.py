from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import uuid
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .backtest_service import DB_PATH, _available_dates, _loads_json, backtest_service
from .config import APP_TIMEZONE
from .signal_pool_service import signal_pool_service


LIVE_ENGINE_VERSION = "live-shadow-v1"
SUPPORTED_MODES = {"observe", "paper", "manual"}
SUPPORTED_STATUSES = {"running", "paused", "stopped", "tripped"}
SUPPORTED_REFRESH_MODES = {"incremental", "full"}
REQUIRED_MATCHED_TRADES = 3
MIN_INCREMENTAL_LOOKBACK_DAYS = 7
MAX_INCREMENTAL_LOOKBACK_DAYS = 90
APP_TZ = ZoneInfo(APP_TIMEZONE)


class LiveStrategyService:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def list_strategies(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, source_backtest_id, source_signal_set_id, mode, status,
                       strategy_package, consistency_check, verification_state,
                       runtime_state, error, created_at, updated_at,
                       started_at, paused_at, stopped_at
                FROM live_strategies
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 100
                """
            ).fetchall()
        return [self._row_to_item(row, compact=True) for row in rows]

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, source_backtest_id, source_signal_set_id, mode, status,
                       strategy_package, consistency_check, verification_state,
                       runtime_state, error, created_at, updated_at,
                       started_at, paused_at, stopped_at
                FROM live_strategies
                WHERE id = ?
                """,
                (strategy_id,),
            ).fetchone()
        return self._row_to_item(row, compact=False) if row else None

    def create_from_backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        backtest_id = str(payload.get("backtest_id") or "").strip()
        if not backtest_id:
            raise ValueError("backtest_id 不能为空")
        mode = self._normalize_mode(payload.get("mode") or "paper")

        backtest = backtest_service.get_run(backtest_id)
        if not backtest:
            raise KeyError(f"回测记录不存在：{backtest_id}")
        if backtest.get("status") != "completed":
            raise ValueError("只能把已完成的回测添加到实盘")

        result = backtest.get("result") if isinstance(backtest.get("result"), dict) else None
        if not result:
            raise ValueError("回测结果为空，无法生成实盘策略包")
        config = backtest.get("config") if isinstance(backtest.get("config"), dict) else {}
        signal_set_ref = result.get("signal_set") if isinstance(result.get("signal_set"), dict) else {}
        signal_set_id = str(config.get("signal_set_id") or signal_set_ref.get("id") or "").strip()
        if not signal_set_id:
            raise ValueError("当前回测缺少 signal_set_id，暂不支持添加到实盘")

        signal_set = signal_pool_service.get_signal_set(signal_set_id)
        if not signal_set:
            raise ValueError(f"来源异动表不存在：{signal_set_id}")
        signal_set_snapshot = self._signal_set_snapshot(signal_set_id)
        if signal_set_snapshot:
            signal_set = {
                **signal_set,
                "config": signal_set_snapshot.get("config") or signal_set.get("config") or {},
                "favorite_snapshot": signal_set_snapshot.get("favorite_snapshot") or {},
                "summary": signal_set_snapshot.get("summary") or signal_set.get("summary") or {},
            }

        package = self._build_strategy_package(backtest, signal_set)
        verification = self._initial_verification_state(package)
        runtime_state = self._initial_runtime_state(result, signal_set, verification)
        compatibility_check = _verification_to_compat_check(verification, package)
        now = _now_ms()
        strategy_id = uuid.uuid4().hex
        requested_name = str(payload.get("name") or "").strip()
        name = requested_name or self._next_live_name()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO live_strategies (
                    id, name, source_backtest_id, source_signal_set_id, mode, status,
                    strategy_package, consistency_check, verification_state,
                    runtime_state, error, created_at, updated_at,
                    started_at, paused_at, stopped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_id,
                    name,
                    backtest["id"],
                    signal_set_id,
                    mode,
                    "paused",
                    _dump_json(package),
                    _dump_json(compatibility_check),
                    _dump_json(verification),
                    _dump_json(runtime_state),
                    "",
                    now,
                    now,
                    None,
                    now,
                    None,
                ),
            )

        item = self.get_strategy(strategy_id)
        if item is None:
            raise RuntimeError("实盘策略写入失败")
        return item

    def _next_live_name(self) -> str:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM live_strategies").fetchall()
        max_index = 0
        for row in rows:
            name = str(row["name"] or "")
            if not name.startswith("实盘v"):
                continue
            suffix = name.removeprefix("实盘v")
            if suffix.isdigit():
                max_index = max(max_index, int(suffix))
        return f"实盘v{max_index + 1:03d}"

    def update_status(self, strategy_id: str, status: str) -> dict[str, Any]:
        normalized = str(status or "").strip().lower()
        if normalized not in SUPPORTED_STATUSES:
            raise ValueError(f"不支持的实盘状态：{status}")
        current = self.get_strategy(strategy_id)
        if not current:
            raise KeyError(f"实盘策略不存在：{strategy_id}")

        now = _now_ms()
        started_at = current.get("started_at")
        paused_at = current.get("paused_at")
        stopped_at = current.get("stopped_at")
        if normalized == "running":
            started_at = started_at or now
            paused_at = None
            stopped_at = None
        elif normalized == "paused":
            paused_at = now
        elif normalized == "stopped":
            stopped_at = now
        elif normalized == "tripped":
            paused_at = now

        state = current.get("runtime_state") if isinstance(current.get("runtime_state"), dict) else {}
        state = {
            **state,
            "last_status_change_at": now,
            "last_status_change_reason": _status_change_reason(normalized),
        }

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE live_strategies
                SET status = ?, runtime_state = ?, updated_at = ?,
                    started_at = ?, paused_at = ?, stopped_at = ?
                WHERE id = ?
                """,
                (
                    normalized,
                    _dump_json(state),
                    now,
                    started_at,
                    paused_at,
                    stopped_at,
                    strategy_id,
                ),
            )

        item = self.get_strategy(strategy_id)
        if item is None:
            raise RuntimeError("实盘策略状态更新失败")
        return item

    def update_mode(self, strategy_id: str, mode: str) -> dict[str, Any]:
        normalized = self._normalize_mode(mode)
        current = self.get_strategy(strategy_id)
        if not current:
            raise KeyError(f"实盘策略不存在：{strategy_id}")
        now = _now_ms()
        state = current.get("runtime_state") if isinstance(current.get("runtime_state"), dict) else {}
        state = {
            **state,
            "last_mode_change_at": now,
            "last_mode": current.get("mode"),
        }
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE live_strategies
                SET mode = ?, runtime_state = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized, _dump_json(state), now, strategy_id),
            )
        item = self.get_strategy(strategy_id)
        if item is None:
            raise RuntimeError("实盘策略模式更新失败")
        return item

    def rename_strategy(self, strategy_id: str, name: str) -> dict[str, Any]:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("实盘策略名称不能为空")
        if len(normalized) > 80:
            raise ValueError("实盘策略名称不能超过 80 个字符")
        current = self.get_strategy(strategy_id)
        if not current:
            raise KeyError(f"实盘策略不存在：{strategy_id}")

        now = _now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE live_strategies
                SET name = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized, now, strategy_id),
            )

        item = self.get_strategy(strategy_id)
        if item is None:
            raise RuntimeError("实盘策略名称更新失败")
        return item

    def run_shadow_verification(self, strategy_id: str) -> dict[str, Any]:
        current = self.get_strategy(strategy_id)
        if not current:
            raise KeyError(f"实盘策略不存在：{strategy_id}")

        package = current.get("strategy_package") if isinstance(current.get("strategy_package"), dict) else {}
        if not package:
            raise ValueError("当前实盘策略缺少冻结策略包")
        package = self._hydrated_strategy_package(current, package)
        current = {**current, "strategy_package": package}

        backtest = backtest_service.get_run(str(current.get("source_backtest_id") or ""))
        if not backtest:
            raise KeyError(f"来源回测不存在：{current.get('source_backtest_id')}")

        run_plan = self._next_shadow_run_plan(strategy_id, package)
        shadow_run_id = uuid.uuid4().hex
        now = _now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO live_shadow_runs (
                    id, strategy_id, shadow_date, data_mode, status,
                    signal_summary, result, error, created_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shadow_run_id,
                    strategy_id,
                    run_plan["shadow_date"],
                    run_plan["data_mode"],
                    "running",
                    "{}",
                    "{}",
                    "",
                    now,
                    None,
                ),
            )

        try:
            signal_set, events = self._build_shadow_signal_set(current, package, shadow_run_id, run_plan)
            shadow_config = self._build_shadow_backtest_config(backtest, package, signal_set)
            shadow_config["name"] = f"实盘连续跟踪回测 {signal_set['config']['start_date']}~{signal_set['config']['end_date']}"
            result = signal_pool_service._execute_signal_backtest(shadow_config, signal_set, events)
            signal_summary = signal_set.get("summary") if isinstance(signal_set.get("summary"), dict) else {}
            finished_at = _now_ms()
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE live_shadow_runs
                    SET status = ?, signal_summary = ?, result = ?, error = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    ("completed", _dump_json(signal_summary), _dump_json(result), "", finished_at, shadow_run_id),
                )
            self._persist_shadow_outputs(strategy_id, shadow_run_id, current, result, events, run_plan)
        except Exception as exc:
            finished_at = _now_ms()
            verification = self._refresh_verification_state(strategy_id, current, error=str(exc))
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE live_shadow_runs
                    SET status = ?, error = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    ("failed", str(exc), finished_at, shadow_run_id),
                )
                conn.execute(
                    """
                    UPDATE live_strategies
                    SET verification_state = ?, consistency_check = ?, runtime_state = ?, error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _dump_json(verification),
                        _dump_json(_verification_to_compat_check(verification, package)),
                        _dump_json(current.get("runtime_state") or {}),
                        str(exc),
                        finished_at,
                        strategy_id,
                    ),
                )
            raise

        updated = self.get_strategy(strategy_id)
        if updated is None:
            raise RuntimeError("影子验证结果更新失败")
        return updated

    # Backward-compatible API name. The operation is no longer a hard replay
    # check against the old backtest; it appends a new shadow tracking run.
    def rerun_consistency_check(self, strategy_id: str) -> dict[str, Any]:
        return self.run_shadow_verification(strategy_id)

    def refresh_backtest_history(self, strategy_id: str, mode: str = "incremental") -> dict[str, Any]:
        refresh_mode = self._normalize_refresh_mode(mode)
        current = self.get_strategy(strategy_id)
        if not current:
            raise KeyError(f"实盘策略不存在：{strategy_id}")

        package = current.get("strategy_package") if isinstance(current.get("strategy_package"), dict) else {}
        if not package:
            raise ValueError("当前实盘策略缺少冻结策略包")
        package = self._hydrated_strategy_package(current, package)
        current = {**current, "strategy_package": package}

        backtest = backtest_service.get_run(str(current.get("source_backtest_id") or ""))
        if not backtest:
            raise KeyError(f"来源回测不存在：{current.get('source_backtest_id')}")

        signal = package.get("signal") if isinstance(package.get("signal"), dict) else {}
        favorite = signal.get("favorite_snapshot") if isinstance(signal.get("favorite_snapshot"), dict) else {}
        if not favorite:
            raise ValueError("冻结策略包缺少收藏条件快照，无法更新回测")
        signal_timeframe = str(signal.get("signal_timeframe") or favorite.get("timeframe") or "")
        available_dates = _available_dates(signal_timeframe)
        if not available_dates:
            raise ValueError(f"{signal_timeframe} 没有可用于更新回测的行情日期")

        start_date = str(signal.get("start_date") or "")
        if not start_date:
            raise ValueError("冻结策略包缺少回测开始日期")
        today = datetime.now(APP_TZ).date().isoformat()
        past_dates = [item for item in available_dates if item < today]
        end_date = (past_dates or available_dates)[-1]
        if end_date < start_date:
            raise ValueError("最新可用日期早于回测开始日期，无法更新")

        refresh_id = uuid.uuid4().hex
        signal_mode = str(signal.get("signal_mode") or "each_bar_close")
        if refresh_mode == "full":
            result, signal_summary, refresh_meta = self._run_full_backtest_refresh(
                backtest=backtest,
                package=package,
                signal=signal,
                favorite=favorite,
                refresh_id=refresh_id,
                start_date=start_date,
                end_date=end_date,
                signal_timeframe=signal_timeframe,
                signal_mode=signal_mode,
            )
        else:
            result, signal_summary, refresh_meta = self._run_incremental_backtest_refresh(
                current=current,
                backtest=backtest,
                package=package,
                signal=signal,
                favorite=favorite,
                refresh_id=refresh_id,
                start_date=start_date,
                end_date=end_date,
                signal_timeframe=signal_timeframe,
                signal_mode=signal_mode,
            )

        now = _now_ms()
        runtime = current.get("runtime_state") if isinstance(current.get("runtime_state"), dict) else {}
        refreshed_runtime = {
            **runtime,
            "refreshed_backtest": {
                "updated_at": now,
                "mode": refresh_mode,
                "refresh_id": refresh_id,
                "start_date": start_date,
                "end_date": end_date,
                "signal_summary": signal_summary,
                "meta": refresh_meta,
                "result": result,
            },
        }
        counters = refreshed_runtime.get("counters") if isinstance(refreshed_runtime.get("counters"), dict) else {}
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        refreshed_runtime["counters"] = {
            **counters,
            "source_backtest_trades": summary.get("total_trades", counters.get("source_backtest_trades", 0)),
        }

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE live_strategies
                SET runtime_state = ?, updated_at = ?
                WHERE id = ?
                """,
                (_dump_json(refreshed_runtime), now, strategy_id),
            )

        item = self.get_strategy(strategy_id)
        if item is None:
            raise RuntimeError("回测刷新结果更新失败")
        return item

    def _run_full_backtest_refresh(
        self,
        *,
        backtest: dict[str, Any],
        package: dict[str, Any],
        signal: dict[str, Any],
        favorite: dict[str, Any],
        refresh_id: str,
        start_date: str,
        end_date: str,
        signal_timeframe: str,
        signal_mode: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        signal_set = self._refresh_signal_set(
            signal=signal,
            favorite=favorite,
            refresh_id=refresh_id,
            start_date=start_date,
            end_date=end_date,
            signal_timeframe=signal_timeframe,
            signal_mode=signal_mode,
            name=f"实盘回测全量重算 {start_date}~{end_date}",
        )
        events, signal_summary = signal_pool_service._build_signal_events(signal_set["id"], favorite, signal_set["config"])
        signal_set["summary"] = signal_summary
        backtest_config = self._build_shadow_backtest_config(backtest, package, signal_set)
        backtest_config["name"] = signal_set["name"]
        result = signal_pool_service._execute_signal_backtest(backtest_config, signal_set, events)
        return (
            result,
            signal_summary,
            {
                "refresh_mode": "full",
                "replay_start_date": start_date,
                "preserved_trade_count": 0,
                "replayed_trade_count": len(result.get("trades") if isinstance(result.get("trades"), list) else []),
                "lookback_days": None,
            },
        )

    def _run_incremental_backtest_refresh(
        self,
        *,
        current: dict[str, Any],
        backtest: dict[str, Any],
        package: dict[str, Any],
        signal: dict[str, Any],
        favorite: dict[str, Any],
        refresh_id: str,
        start_date: str,
        end_date: str,
        signal_timeframe: str,
        signal_mode: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        runtime = current.get("runtime_state") if isinstance(current.get("runtime_state"), dict) else {}
        refreshed = runtime.get("refreshed_backtest") if isinstance(runtime.get("refreshed_backtest"), dict) else {}
        base_result = refreshed.get("result") if isinstance(refreshed.get("result"), dict) else None
        if base_result is None:
            base_result = backtest.get("result") if isinstance(backtest.get("result"), dict) else None
        if not isinstance(base_result, dict):
            raise ValueError("来源回测结果为空，无法增量更新")

        marker_date = str(signal.get("end_date") or "")
        anchor_date = str(refreshed.get("end_date") or marker_date or start_date)
        lookback_days = self._incremental_lookback_days(package, favorite)
        merge_start_date = self._bounded_replay_start(start_date, anchor_date, lookback_days)
        event_start_date = self._bounded_replay_start(start_date, merge_start_date, self._trade_replay_buffer_days(package))
        merge_start_ts = _date_start_ms(merge_start_date)
        event_start_ts = _date_start_ms(event_start_date)

        signal_set = self._refresh_signal_set(
            signal=signal,
            favorite=favorite,
            refresh_id=refresh_id,
            start_date=event_start_date,
            end_date=end_date,
            signal_timeframe=signal_timeframe,
            signal_mode=signal_mode,
            name=f"实盘回测增量重放 {event_start_date}~{end_date}",
        )
        events, signal_summary = self._build_continuous_signal_events(
            current,
            signal_set["id"],
            favorite,
            signal_set["config"],
            marker_date,
            end_date,
            min_date=event_start_date,
        )
        signal_set["summary"] = signal_summary
        backtest_config = self._build_shadow_backtest_config(backtest, package, signal_set)
        backtest_config["name"] = signal_set["name"]

        base_trades = base_result.get("trades") if isinstance(base_result.get("trades"), list) else []
        prior_trades = [trade for trade in base_trades if isinstance(trade, dict) and (_safe_int(trade.get("exit_ts")) or 0) < merge_start_ts]
        boundary_trades = [
            trade
            for trade in base_trades
            if isinstance(trade, dict)
            and (_safe_int(trade.get("confirm_ts")) or 0) < event_start_ts
            and (_safe_int(trade.get("exit_ts")) or 0) >= merge_start_ts
        ]
        realized_before_replay = sum(
            float(trade.get("pnl_usdt") or 0)
            for trade in base_trades
            if isinstance(trade, dict)
            and (_safe_int(trade.get("exit_ts")) or 0) <= event_start_ts
        )
        carried_positions = [
            {
                "inst_id": trade.get("inst_id"),
                "exit_ts": trade.get("exit_ts"),
                "pnl_usdt": trade.get("pnl_usdt"),
            }
            for trade in base_trades
            if isinstance(trade, dict)
            and (_safe_int(trade.get("entry_ts")) or 0) < event_start_ts
            and (_safe_int(trade.get("exit_ts")) or 0) > event_start_ts
        ]
        replay_result = signal_pool_service._execute_signal_backtest(
            backtest_config,
            signal_set,
            events,
            {
                "realized_pnl": realized_before_replay,
                "open_positions": carried_positions,
            },
        )
        replay_trades = replay_result.get("trades") if isinstance(replay_result.get("trades"), list) else []
        replay_kept_trades = [
            trade
            for trade in replay_trades
            if isinstance(trade, dict) and (_safe_int(trade.get("exit_ts")) or 0) >= merge_start_ts
        ]
        merged_trades = _renumber_trades([*prior_trades, *boundary_trades, *replay_kept_trades])
        merged_checkpoints = self._merged_refresh_checkpoints(base_result, replay_result, merge_start_ts)
        merged_signal_summary = self._merged_refresh_signal_summary(
            base_result=base_result,
            replay_summary=signal_summary,
            checkpoints=merged_checkpoints,
            new_event_count=sum(1 for event in events if str(event.get("confirm_time") or "")[:10] > anchor_date),
            new_checkpoint_count=len({int(event.get("confirm_ts") or 0) for event in events if str(event.get("confirm_time") or "")[:10] > anchor_date}),
            start_date=start_date,
            end_date=end_date,
            signal_timeframe=signal_timeframe,
            signal_mode=signal_mode,
            preserved_trades=prior_trades,
            replay_trades=replay_kept_trades,
        )
        merged_signal_set = {
            **signal_set,
            "name": f"实盘回测增量结果 {start_date}~{end_date}",
            "config": {
                **signal_set["config"],
                "start_date": start_date,
                "end_date": end_date,
                "name": f"实盘回测增量结果 {start_date}~{end_date}",
            },
            "summary": merged_signal_summary,
        }
        counters = self._merged_refresh_counters(base_result, replay_result, merged_signal_summary, merged_trades)
        summary, equity, daily_equity = signal_pool_service._summarize(backtest_config, merged_signal_set, counters, merged_trades)
        summary["duration_ms"] = int((base_result.get("summary") or {}).get("duration_ms") or 0) + int((replay_result.get("summary") or {}).get("duration_ms") or 0)
        result = {
            "summary": summary,
            "equity": equity,
            "daily_equity": daily_equity,
            "trades": merged_trades,
            "checkpoints": merged_checkpoints,
            "favorite": signal_set.get("favorite"),
            "signal_set": {
                "id": signal_set["id"],
                "name": merged_signal_set["name"],
                "summary": merged_signal_summary,
            },
        }
        return (
            result,
            merged_signal_summary,
            {
                "refresh_mode": "incremental",
                "anchor_date": anchor_date,
                "merge_start_date": merge_start_date,
                "replay_start_date": event_start_date,
                "lookback_days": lookback_days,
                "trade_replay_buffer_days": self._trade_replay_buffer_days(package),
                "carried_open_positions": len(carried_positions),
                "preserved_trade_count": len(prior_trades),
                "boundary_trade_count": len(boundary_trades),
                "replayed_trade_count": len(replay_kept_trades),
                "merged_trade_count": len(merged_trades),
            },
        )

    def _refresh_signal_set(
        self,
        *,
        signal: dict[str, Any],
        favorite: dict[str, Any],
        refresh_id: str,
        start_date: str,
        end_date: str,
        signal_timeframe: str,
        signal_mode: str,
        name: str,
    ) -> dict[str, Any]:
        return {
            "id": f"live_refresh_{refresh_id}",
            "favorite_id": str(signal.get("favorite_id") or favorite.get("id") or ""),
            "name": name,
            "status": "completed",
            "config": {
                "favorite_id": str(signal.get("favorite_id") or favorite.get("id") or ""),
                "favorite_name": str(favorite.get("name") or ""),
                "name": name,
                "start_date": start_date,
                "end_date": end_date,
                "signal_timeframe": signal_timeframe,
                "signal_mode": signal_mode,
                "checkpoint_limit": int(signal.get("checkpoint_limit") or 5000),
            },
            "favorite": favorite,
            "summary": {},
            "error": "",
        }

    def _incremental_lookback_days(self, package: dict[str, Any], favorite: dict[str, Any]) -> int:
        entry = package.get("entry") if isinstance(package.get("entry"), dict) else {}
        exit_cfg = package.get("exit") if isinstance(package.get("exit"), dict) else {}
        signal = package.get("signal") if isinstance(package.get("signal"), dict) else {}
        minutes = int(entry.get("entry_window_minutes") or 0) + int(exit_cfg.get("exit_hold_minutes") or 0)
        lookback = math.ceil(minutes / (24 * 60)) + 3
        signal_step = _timeframe_minutes(str(signal.get("signal_timeframe") or favorite.get("timeframe") or "1H")) or 60
        for condition in favorite.get("metadata_conditions") or []:
            if not isinstance(condition, dict):
                continue
            if condition.get("time_mode") == "previous_trading_day":
                lookback = max(lookback, int(condition.get("time_offset") or 1) + 2)
            indicator = condition.get("indicator") if isinstance(condition.get("indicator"), dict) else {}
            period = str(indicator.get("storage_period") or signal.get("signal_timeframe") or favorite.get("timeframe") or "1H")
            period_minutes = _timeframe_minutes(period) or signal_step
            mode = str(condition.get("time_point_mode") or "").strip().lower()
            if mode == "bar_offset":
                lookback = max(lookback, math.ceil(int(condition.get("bar_offset") or 0) * period_minutes / (24 * 60)) + 2)
            elif mode == "time_offset":
                unit = str(condition.get("time_offset_unit") or "hour").strip().lower()
                unit_minutes = 1 if unit in ("minute", "minutes", "m", "分钟") else 60
                lookback = max(lookback, math.ceil(int(condition.get("time_offset_value") or 0) * unit_minutes / (24 * 60)) + 2)
        return max(MIN_INCREMENTAL_LOOKBACK_DAYS, min(MAX_INCREMENTAL_LOOKBACK_DAYS, lookback))

    def _trade_replay_buffer_days(self, package: dict[str, Any]) -> int:
        entry = package.get("entry") if isinstance(package.get("entry"), dict) else {}
        exit_cfg = package.get("exit") if isinstance(package.get("exit"), dict) else {}
        minutes = int(entry.get("entry_window_minutes") or 0) + int(exit_cfg.get("exit_hold_minutes") or 0)
        return max(2, min(MAX_INCREMENTAL_LOOKBACK_DAYS, math.ceil(minutes / (24 * 60)) + 2))

    def _bounded_replay_start(self, start_date: str, anchor_date: str, lookback_days: int) -> str:
        try:
            start = Date.fromisoformat(start_date)
            anchor = Date.fromisoformat(anchor_date)
        except ValueError:
            return start_date
        replay = anchor - timedelta(days=lookback_days)
        if replay < start:
            replay = start
        return replay.isoformat()

    def _merged_refresh_signal_summary(
        self,
        *,
        base_result: dict[str, Any],
        replay_summary: dict[str, Any],
        checkpoints: list[dict[str, Any]],
        new_event_count: int,
        new_checkpoint_count: int,
        start_date: str,
        end_date: str,
        signal_timeframe: str,
        signal_mode: str,
        preserved_trades: list[dict[str, Any]],
        replay_trades: list[dict[str, Any]],
    ) -> dict[str, Any]:
        base_signal = base_result.get("signal_set") if isinstance(base_result.get("signal_set"), dict) else {}
        base_summary = base_signal.get("summary") if isinstance(base_signal.get("summary"), dict) else {}
        checkpoint_events = sum(int(item.get("matched_count") or 0) for item in checkpoints if isinstance(item, dict))
        checkpoint_opened = sum(int(item.get("opened_count") or 0) for item in checkpoints if isinstance(item, dict))
        base_event_count = int(base_summary.get("event_count") or base_summary.get("matched_count") or 0)
        base_checkpoint_count = int(base_summary.get("checkpoint_count") or 0)
        return {
            **base_summary,
            "start_date": start_date,
            "end_date": end_date,
            "signal_timeframe": signal_timeframe,
            "signal_mode": signal_mode,
            "checkpoint_count": base_checkpoint_count + new_checkpoint_count,
            "matched_count": base_event_count + new_event_count,
            "returned_count": base_event_count + new_event_count,
            "event_count": base_event_count + new_event_count,
            "opened_count": checkpoint_opened,
            "truncated_events": max(int(base_summary.get("truncated_events") or 0), int(replay_summary.get("truncated_events") or 0)),
            "unique_contracts": None,
            "total_contracts": replay_summary.get("total_contracts") or base_summary.get("total_contracts"),
            "last_signal_ts": replay_summary.get("last_signal_ts") or base_summary.get("last_signal_ts"),
            "last_signal_time": replay_summary.get("last_signal_time") or base_summary.get("last_signal_time"),
            "last_confirm_ts": replay_summary.get("last_confirm_ts") or base_summary.get("last_confirm_ts"),
            "last_confirm_time": replay_summary.get("last_confirm_time") or base_summary.get("last_confirm_time"),
            "duration_ms": int(base_summary.get("duration_ms") or 0) + int(replay_summary.get("duration_ms") or 0),
            "incremental_preserved_trades": len(preserved_trades),
            "incremental_replayed_trades": len(replay_trades),
        }

    def _merged_refresh_counters(
        self,
        base_result: dict[str, Any],
        replay_result: dict[str, Any],
        signal_summary: dict[str, Any],
        trades: list[dict[str, Any]],
    ) -> dict[str, int]:
        base_summary = base_result.get("summary") if isinstance(base_result.get("summary"), dict) else {}
        replay_summary = replay_result.get("summary") if isinstance(replay_result.get("summary"), dict) else {}
        counters: dict[str, int] = {
            "checkpoints": int(signal_summary.get("checkpoint_count") or 0),
            "matched_signals": int(signal_summary.get("event_count") or signal_summary.get("matched_count") or 0),
            "opened_trades": len(trades),
        }
        for key in (
            "skipped_overlap",
            "skipped_max_positions",
            "skipped_insufficient_equity",
            "skipped_account_depleted",
            "skipped_no_entry",
            "skipped_no_exit",
            "skipped_entry_rule",
        ):
            counters[key] = max(int(base_summary.get(key) or 0), int(replay_summary.get(key) or 0))
        return counters

    def _merged_refresh_checkpoints(
        self,
        base_result: dict[str, Any],
        replay_result: dict[str, Any],
        replay_start_ts: int,
    ) -> list[dict[str, Any]]:
        base_items = base_result.get("checkpoints") if isinstance(base_result.get("checkpoints"), list) else []
        replay_items = replay_result.get("checkpoints") if isinstance(replay_result.get("checkpoints"), list) else []
        preserved = [
            item
            for item in base_items
            if isinstance(item, dict) and (_safe_int(item.get("signal_ts")) or _safe_int(item.get("confirm_ts")) or 0) < replay_start_ts
        ]
        merged = [*preserved, *[item for item in replay_items if isinstance(item, dict)]]
        merged.sort(key=lambda item: (_safe_int(item.get("signal_ts")) or _safe_int(item.get("confirm_ts")) or 0, str(item.get("date") or "")))
        return [{**item, "index": index} for index, item in enumerate(merged[-100:], start=1)]

    def _build_strategy_package(self, backtest: dict[str, Any], signal_set: dict[str, Any]) -> dict[str, Any]:
        result = backtest.get("result") if isinstance(backtest.get("result"), dict) else {}
        config = backtest.get("config") if isinstance(backtest.get("config"), dict) else {}
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        trades = result.get("trades") if isinstance(result.get("trades"), list) else []
        favorite_snapshot = (
            signal_set.get("favorite_snapshot")
            if isinstance(signal_set.get("favorite_snapshot"), dict)
            else signal_set.get("favorite") if isinstance(signal_set.get("favorite"), dict) else {}
        )
        signal_config = signal_set.get("config") if isinstance(signal_set.get("config"), dict) else {}

        signal = {
            "signal_set_id": signal_set["id"],
            "favorite_id": signal_set.get("favorite_id"),
            "favorite_snapshot": favorite_snapshot,
            "signal_timeframe": signal_config.get("signal_timeframe") or config.get("signal_timeframe"),
            "signal_mode": signal_config.get("signal_mode") or config.get("signal_mode"),
            "start_date": signal_config.get("start_date") or summary.get("start_date"),
            "end_date": signal_config.get("end_date") or summary.get("end_date"),
            "checkpoint_limit": signal_config.get("checkpoint_limit"),
        }
        entry = {
            "side": config.get("side", "short"),
            "entry_timeframe": config.get("entry_timeframe"),
            "entry_rule": config.get("entry_rule"),
            "entry_window_minutes": config.get("entry_window_minutes"),
            "entry_consecutive_bars": config.get("entry_consecutive_bars"),
            "entry_min_gain_pct_each": config.get("entry_min_gain_pct_each"),
        }
        exit_cfg = {
            "exit_hold_minutes": config.get("exit_hold_minutes"),
            "stop_loss_pct": config.get("stop_loss_pct"),
            "stop_model": config.get("stop_model"),
        }
        risk = {
            "position_usdt": config.get("position_usdt"),
            "leverage": config.get("leverage"),
            "max_positions": config.get("max_positions"),
            "fee_bps_per_side": config.get("fee_bps_per_side"),
            "slippage_bps_per_side": config.get("slippage_bps_per_side"),
            "max_same_symbol_positions": 1,
        }
        audit_payload = {
            "backtest_id": backtest["id"],
            "config": config,
            "summary": summary,
            "trades": trades,
        }
        package = {
            "engine_version": LIVE_ENGINE_VERSION,
            "source_backtest_id": backtest["id"],
            "source_backtest_name": backtest.get("name", ""),
            "source_backtest_created_at": backtest.get("created_at"),
            "source_result_hash": _hash_payload(audit_payload),
            "signal": signal,
            "entry": entry,
            "exit": exit_cfg,
            "risk": risk,
            "backtest_summary": summary,
            "created_from_result": {
                "total_trades": summary.get("total_trades"),
                "total_pnl": summary.get("total_pnl"),
                "total_return_pct": summary.get("total_return_pct"),
                "max_drawdown_pct": summary.get("max_drawdown_pct"),
                "win_rate": summary.get("win_rate"),
            },
        }
        package["package_hash"] = _hash_payload({key: value for key, value in package.items() if key != "package_hash"})
        return package

    def _hydrated_strategy_package(self, strategy: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
        signal = package.get("signal") if isinstance(package.get("signal"), dict) else {}
        favorite = signal.get("favorite_snapshot") if isinstance(signal.get("favorite_snapshot"), dict) else {}
        if favorite.get("metadata_conditions"):
            return package
        snapshot = self._signal_set_snapshot(str(strategy.get("source_signal_set_id") or signal.get("signal_set_id") or ""))
        snapshot_favorite = snapshot.get("favorite_snapshot") if isinstance(snapshot, dict) else {}
        if not isinstance(snapshot_favorite, dict) or not snapshot_favorite.get("metadata_conditions"):
            return package
        hydrated_signal = {
            **signal,
            "favorite_snapshot": snapshot_favorite,
        }
        hydrated = {
            **package,
            "signal": hydrated_signal,
        }
        hydrated["package_hash"] = _hash_payload({key: value for key, value in hydrated.items() if key != "package_hash"})
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE live_strategies
                SET strategy_package = ?, updated_at = ?
                WHERE id = ?
                """,
                (_dump_json(hydrated), _now_ms(), strategy["id"]),
            )
        return hydrated

    def _signal_set_snapshot(self, signal_set_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT config, favorite_snapshot, summary
                FROM signal_sets
                WHERE id = ?
                """,
                (signal_set_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "config": _loads_json(row["config"], {}),
            "favorite_snapshot": _loads_json(row["favorite_snapshot"], {}),
            "summary": _loads_json(row["summary"], {}),
        }

    def _next_shadow_run_plan(self, strategy_id: str, package: dict[str, Any]) -> dict[str, str]:
        signal = package.get("signal") if isinstance(package.get("signal"), dict) else {}
        timeframe = str(signal.get("signal_timeframe") or "")
        if not timeframe:
            raise ValueError("冻结策略包缺少 signal_timeframe")
        dates = _available_dates(timeframe)
        if not dates:
            raise ValueError(f"{timeframe} 没有可用于影子跟踪的行情日期")

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT shadow_date
                FROM live_shadow_runs
                WHERE strategy_id = ? AND status = ?
                ORDER BY shadow_date DESC
                LIMIT 1
                """,
                (strategy_id, "completed"),
            ).fetchone()
        last_shadow_date = str(row["shadow_date"]) if row else ""
        source_end_date = str(signal.get("end_date") or "")
        source_start_date = str(signal.get("start_date") or "")
        if not source_start_date:
            raise ValueError("冻结策略包缺少 start_date")
        anchor = last_shadow_date or source_end_date

        if anchor:
            for item in dates:
                if item > anchor:
                    return {
                        "shadow_date": item,
                        "start_date": source_start_date,
                        "end_date": item,
                        "marker_date": source_end_date,
                        "data_mode": "forward_continuous",
                    }

        if not last_shadow_date:
            fallback = source_end_date if source_end_date in dates else dates[-1]
            return {
                "shadow_date": fallback,
                "start_date": source_start_date,
                "end_date": fallback,
                "marker_date": source_end_date,
                "data_mode": "latest_available_continuous",
            }

        if last_shadow_date:
            return {
                "shadow_date": last_shadow_date,
                "start_date": source_start_date,
                "end_date": last_shadow_date,
                "marker_date": source_end_date,
                "data_mode": "rebuild_latest_continuous",
            }

        raise ValueError("暂无新的行情日期可生成下一轮跟踪回测")

    def _build_shadow_signal_set(
        self,
        strategy: dict[str, Any],
        package: dict[str, Any],
        shadow_run_id: str,
        run_plan: dict[str, str],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        signal = package.get("signal") if isinstance(package.get("signal"), dict) else {}
        favorite = signal.get("favorite_snapshot") if isinstance(signal.get("favorite_snapshot"), dict) else {}
        if not favorite:
            raise ValueError("冻结策略包缺少收藏条件快照，无法生成跟踪异动")
        signal_timeframe = str(signal.get("signal_timeframe") or favorite.get("timeframe") or "")
        signal_mode = str(signal.get("signal_mode") or "each_bar_close")
        start_date = str(run_plan.get("start_date") or signal.get("start_date") or run_plan.get("end_date") or "")
        end_date = str(run_plan.get("end_date") or run_plan.get("shadow_date") or "")
        marker_date = str(run_plan.get("marker_date") or signal.get("end_date") or "")
        config = {
            "favorite_id": str(signal.get("favorite_id") or favorite.get("id") or ""),
            "favorite_name": str(favorite.get("name") or ""),
            "name": f"实盘影子异动 {end_date}",
            "start_date": start_date,
            "end_date": end_date,
            "signal_timeframe": signal_timeframe,
            "signal_mode": signal_mode,
            "checkpoint_limit": int(signal.get("checkpoint_limit") or 5000),
        }
        signal_set = {
            "id": f"live_shadow_{shadow_run_id}",
            "favorite_id": config["favorite_id"],
            "name": config["name"],
            "status": "completed",
            "config": config,
            "favorite": favorite,
            "summary": {},
            "error": "",
        }
        events, summary = self._build_continuous_signal_events(
            strategy,
            signal_set["id"],
            favorite,
            config,
            marker_date,
            end_date,
        )
        signal_set["summary"] = summary
        return signal_set, events

    def _build_continuous_signal_events(
        self,
        strategy: dict[str, Any],
        signal_set_id: str,
        favorite: dict[str, Any],
        config: dict[str, Any],
        marker_date: str,
        end_date: str,
        *,
        min_date: str = "",
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        source_events = self._source_signal_events(str(strategy.get("source_signal_set_id") or ""))
        min_date = min_date or str(config.get("start_date") or "")
        historical_events = [
            {**event, "signal_set_id": signal_set_id}
            for event in source_events
            if (not min_date or str(event.get("confirm_time") or "")[:10] >= min_date)
            and str(event.get("confirm_time") or "")[:10] <= marker_date
        ]
        forward_events: list[dict[str, Any]] = []
        forward_summary: dict[str, Any] = {}
        forward_start_date = max(_next_date(marker_date), min_date) if min_date else _next_date(marker_date)
        if end_date >= forward_start_date:
            forward_config = {
                **config,
                "start_date": forward_start_date,
                "end_date": end_date,
            }
            forward_events, forward_summary = signal_pool_service._build_signal_events(signal_set_id, favorite, forward_config)
        for event in forward_events:
            event["signal_set_id"] = signal_set_id
        events = [*historical_events, *forward_events]
        events.sort(key=lambda item: (int(item.get("confirm_ts") or 0), -float(item.get("strength") or 0), str(item.get("inst_id") or "")))
        historical_summary = self._signal_event_summary(historical_events)
        summary = self._merge_signal_summaries(config, historical_summary, forward_summary, events)
        return events, summary

    def _source_signal_events(self, signal_set_id: str) -> list[dict[str, Any]]:
        if not signal_set_id:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, signal_set_id, favorite_id, inst_id, timeframe, date,
                       signal_ts, confirm_ts, signal_time, confirm_time, strength,
                       matched_conditions, metadata_values, row_snapshot
                FROM signal_events
                WHERE signal_set_id = ?
                ORDER BY confirm_ts ASC, strength DESC, inst_id ASC
                """,
                (signal_set_id,),
            ).fetchall()
        return [
            {
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
            for row in rows
        ]

    def _signal_event_summary(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "checkpoint_count": len({int(event.get("confirm_ts") or 0) for event in events}),
            "matched_count": len(events),
            "returned_count": len(events),
            "event_count": len(events),
            "truncated_events": 0,
            "unique_contracts": len({str(event.get("inst_id") or "") for event in events if event.get("inst_id")}),
            "total_contracts": None,
            "first_signal_ts": events[0].get("signal_ts") if events else None,
            "first_signal_time": events[0].get("signal_time") if events else None,
            "last_signal_ts": events[-1].get("signal_ts") if events else None,
            "last_signal_time": events[-1].get("signal_time") if events else None,
            "first_confirm_ts": events[0].get("confirm_ts") if events else None,
            "first_confirm_time": events[0].get("confirm_time") if events else None,
            "last_confirm_ts": events[-1].get("confirm_ts") if events else None,
            "last_confirm_time": events[-1].get("confirm_time") if events else None,
            "duration_ms": 0,
        }

    def _merge_signal_summaries(
        self,
        config: dict[str, Any],
        historical: dict[str, Any],
        forward: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "start_date": config["start_date"],
            "end_date": config["end_date"],
            "signal_timeframe": config["signal_timeframe"],
            "signal_mode": config["signal_mode"],
            "checkpoint_count": int(historical.get("checkpoint_count") or 0) + int(forward.get("checkpoint_count") or 0),
            "matched_count": int(historical.get("matched_count") or 0) + int(forward.get("matched_count") or 0),
            "returned_count": int(historical.get("returned_count") or 0) + int(forward.get("returned_count") or 0),
            "event_count": len(events),
            "truncated_events": int(historical.get("truncated_events") or 0) + int(forward.get("truncated_events") or 0),
            "unique_contracts": len({str(event.get("inst_id") or "") for event in events if event.get("inst_id")}),
            "total_contracts": forward.get("total_contracts") or historical.get("total_contracts"),
            "first_signal_ts": events[0].get("signal_ts") if events else None,
            "first_signal_time": events[0].get("signal_time") if events else None,
            "last_signal_ts": events[-1].get("signal_ts") if events else None,
            "last_signal_time": events[-1].get("signal_time") if events else None,
            "first_confirm_ts": events[0].get("confirm_ts") if events else None,
            "first_confirm_time": events[0].get("confirm_time") if events else None,
            "last_confirm_ts": events[-1].get("confirm_ts") if events else None,
            "last_confirm_time": events[-1].get("confirm_time") if events else None,
            "duration_ms": int(historical.get("duration_ms") or 0) + int(forward.get("duration_ms") or 0),
        }

    def _build_shadow_backtest_config(
        self,
        backtest: dict[str, Any],
        package: dict[str, Any],
        signal_set: dict[str, Any],
    ) -> dict[str, Any]:
        original = backtest.get("config") if isinstance(backtest.get("config"), dict) else {}
        entry = package.get("entry") if isinstance(package.get("entry"), dict) else {}
        exit_cfg = package.get("exit") if isinstance(package.get("exit"), dict) else {}
        risk = package.get("risk") if isinstance(package.get("risk"), dict) else {}
        config = {
            **original,
            "signal_set_id": signal_set["id"],
            "favorite_id": signal_set["favorite_id"],
            "favorite_name": (signal_set.get("favorite") or {}).get("name", ""),
            "name": f"实盘跟踪回测 {signal_set['config']['start_date']}",
            "side": entry.get("side", original.get("side", "short")),
            "entry_timeframe": entry.get("entry_timeframe") or original.get("entry_timeframe"),
            "entry_rule": entry.get("entry_rule") or original.get("entry_rule"),
            "entry_window_minutes": entry.get("entry_window_minutes") or original.get("entry_window_minutes"),
            "entry_consecutive_bars": entry.get("entry_consecutive_bars") or original.get("entry_consecutive_bars"),
            "entry_min_gain_pct_each": entry.get("entry_min_gain_pct_each") if entry.get("entry_min_gain_pct_each") is not None else original.get("entry_min_gain_pct_each"),
            "exit_hold_minutes": exit_cfg.get("exit_hold_minutes") or original.get("exit_hold_minutes"),
            "stop_loss_pct": exit_cfg.get("stop_loss_pct") if exit_cfg.get("stop_loss_pct") is not None else original.get("stop_loss_pct"),
            "stop_model": exit_cfg.get("stop_model") or original.get("stop_model"),
            "position_usdt": risk.get("position_usdt") or original.get("position_usdt"),
            "leverage": risk.get("leverage") or original.get("leverage"),
            "max_positions": risk.get("max_positions") or original.get("max_positions"),
            "fee_bps_per_side": risk.get("fee_bps_per_side") if risk.get("fee_bps_per_side") is not None else original.get("fee_bps_per_side"),
            "slippage_bps_per_side": risk.get("slippage_bps_per_side") if risk.get("slippage_bps_per_side") is not None else original.get("slippage_bps_per_side"),
        }
        exit_hold_minutes = int(config.get("exit_hold_minutes") or 0)
        config["hold_hours"] = round(exit_hold_minutes / 60, 4)
        return config

    def _persist_shadow_outputs(
        self,
        strategy_id: str,
        shadow_run_id: str,
        strategy: dict[str, Any],
        result: dict[str, Any],
        events: list[dict[str, Any]],
        run_plan: dict[str, str],
    ) -> None:
        all_trades = result.get("trades") if isinstance(result.get("trades"), list) else []
        mode = str(strategy.get("mode") or "observe")
        marker_date = str(run_plan.get("marker_date") or "")
        shadow_date = str(run_plan.get("shadow_date") or "")
        trades = [
            trade
            for trade in all_trades
            if _trade_date(trade) > marker_date and (not shadow_date or _trade_date(trade) <= shadow_date)
        ]
        shadow_records: list[dict[str, Any]] = []
        live_records: list[dict[str, Any]] = []
        now = _now_ms()

        with self._connect() as conn:
            self._delete_rebuilt_tracking_records(conn, strategy_id)
            for offset, trade in enumerate(trades, start=1):
                sequence_no = offset
                shadow_record = self._trade_record_payload(
                    strategy_id=strategy_id,
                    shadow_run_id=shadow_run_id,
                    source="shadow_backtest",
                    sequence_no=sequence_no,
                    trade=trade,
                    status="closed",
                    created_at=now,
                )
                self._insert_trade_record(conn, shadow_record)
                shadow_records.append(shadow_record)

                if mode in SUPPORTED_MODES:
                    live_trade = {
                        **trade,
                        "live_source": "paper_tracking",
                        "live_mode": mode,
                        "paper_fill": True,
                    }
                    live_record = self._trade_record_payload(
                        strategy_id=strategy_id,
                        shadow_run_id=shadow_run_id,
                        source="paper_live",
                        sequence_no=sequence_no,
                        trade=live_trade,
                        status="closed",
                        created_at=now,
                    )
                    self._insert_trade_record(conn, live_record)
                    live_records.append(live_record)

            for shadow_record in shadow_records:
                live_record = next(
                    (item for item in live_records if int(item["sequence_no"]) == int(shadow_record["sequence_no"])),
                    None,
                )
                check = self._reconcile_record_payload(strategy_id, shadow_record, live_record, now)
                conn.execute(
                    """
                    INSERT INTO live_reconcile_checks (
                        id, strategy_id, shadow_trade_id, live_trade_id, sequence_no,
                        status, mismatches, tolerance, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        check["id"],
                        check["strategy_id"],
                        check["shadow_trade_id"],
                        check["live_trade_id"],
                        check["sequence_no"],
                        check["status"],
                        _dump_json(check["mismatches"]),
                        _dump_json(check["tolerance"]),
                        check["created_at"],
                    ),
                )

        updated = self.get_strategy(strategy_id)
        if not updated:
            return
        verification = self._refresh_verification_state(strategy_id, updated)
        runtime = self._refresh_runtime_state(strategy_id, updated, result, events)
        package = updated.get("strategy_package") if isinstance(updated.get("strategy_package"), dict) else {}
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE live_strategies
                SET verification_state = ?, consistency_check = ?, runtime_state = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    _dump_json(verification),
                    _dump_json(_verification_to_compat_check(verification, package)),
                    _dump_json(runtime),
                    "",
                    _now_ms(),
                    strategy_id,
                ),
            )

    def _trade_record_payload(
        self,
        *,
        strategy_id: str,
        shadow_run_id: str,
        source: str,
        sequence_no: int,
        trade: dict[str, Any],
        status: str,
        created_at: int,
    ) -> dict[str, Any]:
        payload = {**trade, "sequence_no": sequence_no, "record_source": source}
        return {
            "id": uuid.uuid4().hex,
            "strategy_id": strategy_id,
            "shadow_run_id": shadow_run_id,
            "source": source,
            "sequence_no": sequence_no,
            "trade_key": _trade_key(strategy_id, source, sequence_no, trade),
            "inst_id": str(trade.get("inst_id") or ""),
            "side": str(trade.get("side") or ""),
            "status": status,
            "signal_ts": _safe_int(trade.get("signal_ts")),
            "confirm_ts": _safe_int(trade.get("confirm_ts")),
            "entry_ts": _safe_int(trade.get("entry_ts")),
            "exit_ts": _safe_int(trade.get("exit_ts")),
            "entry_price": _safe_float(trade.get("entry_price") if trade.get("entry_price") is not None else trade.get("raw_entry_price")),
            "exit_price": _safe_float(trade.get("exit_price") if trade.get("exit_price") is not None else trade.get("raw_exit_price")),
            "pnl_usdt": _safe_float(trade.get("pnl_usdt")),
            "payload": payload,
            "created_at": created_at,
        }

    def _insert_trade_record(self, conn: sqlite3.Connection, record: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO live_trade_records (
                id, strategy_id, shadow_run_id, source, sequence_no, trade_key,
                inst_id, side, status, signal_ts, confirm_ts, entry_ts, exit_ts,
                entry_price, exit_price, pnl_usdt, payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["strategy_id"],
                record["shadow_run_id"],
                record["source"],
                record["sequence_no"],
                record["trade_key"],
                record["inst_id"],
                record["side"],
                record["status"],
                record["signal_ts"],
                record["confirm_ts"],
                record["entry_ts"],
                record["exit_ts"],
                record["entry_price"],
                record["exit_price"],
                record["pnl_usdt"],
                _dump_json(record["payload"]),
                record["created_at"],
            ),
        )

    def _reconcile_record_payload(
        self,
        strategy_id: str,
        shadow_record: dict[str, Any],
        live_record: dict[str, Any] | None,
        created_at: int,
    ) -> dict[str, Any]:
        tolerance = {
            "time_ms": 0,
            "price_pct": 0.05,
            "pnl_usdt": 1.0,
        }
        if live_record is None:
            return {
                "id": uuid.uuid4().hex,
                "strategy_id": strategy_id,
                "shadow_trade_id": shadow_record["id"],
                "live_trade_id": None,
                "sequence_no": shadow_record["sequence_no"],
                "status": "pending",
                "mismatches": [{"field": "live_trade", "message": "等待实盘/纸面交易记录"}],
                "tolerance": tolerance,
                "created_at": created_at,
            }
        mismatches = _compare_trade_payloads(shadow_record["payload"], live_record["payload"], tolerance)
        return {
            "id": uuid.uuid4().hex,
            "strategy_id": strategy_id,
            "shadow_trade_id": shadow_record["id"],
            "live_trade_id": live_record["id"],
            "sequence_no": shadow_record["sequence_no"],
            "status": "passed" if not mismatches else "failed",
            "mismatches": mismatches,
            "tolerance": tolerance,
            "created_at": created_at,
        }

    def _max_trade_sequence(self, strategy_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(sequence_no) AS max_sequence
                FROM live_trade_records
                WHERE strategy_id = ? AND source = ?
                """,
                (strategy_id, "shadow_backtest"),
            ).fetchone()
        return int(row["max_sequence"] or 0) if row else 0

    def _delete_rebuilt_tracking_records(self, conn: sqlite3.Connection, strategy_id: str) -> None:
        conn.execute("DELETE FROM live_reconcile_checks WHERE strategy_id = ?", (strategy_id,))
        conn.execute(
            """
            DELETE FROM live_trade_records
            WHERE strategy_id = ?
              AND source IN ('shadow_backtest', 'paper_live')
            """,
            (strategy_id,),
        )

    def _initial_verification_state(self, package: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "shadow_verifying",
            "required_matches": REQUIRED_MATCHED_TRADES,
            "matched_trades": 0,
            "consecutive_matches": 0,
            "total_checks": 0,
            "passed_checks": 0,
            "failed_checks": 0,
            "pending_checks": 0,
            "shadow_runs": 0,
            "last_shadow_date": None,
            "last_shadow_run_id": None,
            "last_run_at": None,
            "last_message": "策略包已冻结，等待生成每日跟踪回测并与实盘/纸面交易对账。",
            "package_hash": package.get("package_hash"),
        }

    def _refresh_verification_state(
        self,
        strategy_id: str,
        strategy: dict[str, Any],
        *,
        error: str = "",
    ) -> dict[str, Any]:
        package = strategy.get("strategy_package") if isinstance(strategy.get("strategy_package"), dict) else {}
        with self._connect() as conn:
            run_rows = conn.execute(
                """
                SELECT id, shadow_date, data_mode, status, error, created_at, finished_at
                FROM live_shadow_runs
                WHERE strategy_id = ?
                ORDER BY created_at ASC
                """,
                (strategy_id,),
            ).fetchall()
            check_rows = conn.execute(
                """
                SELECT sequence_no, status, mismatches, created_at
                FROM live_reconcile_checks
                WHERE strategy_id = ?
                ORDER BY sequence_no ASC, created_at ASC
                """,
                (strategy_id,),
            ).fetchall()

        checks = [
            {
                "sequence_no": int(row["sequence_no"] or 0),
                "status": row["status"],
                "mismatches": _loads_json(row["mismatches"], []),
                "created_at": row["created_at"],
            }
            for row in check_rows
        ]
        passed_checks = sum(1 for item in checks if item["status"] == "passed")
        failed_checks = sum(1 for item in checks if item["status"] == "failed")
        pending_checks = sum(1 for item in checks if item["status"] == "pending")
        consecutive = 0
        for item in checks:
            if item["status"] == "passed":
                consecutive += 1
            elif item["status"] == "failed":
                consecutive = 0
        latest_check_status = checks[-1]["status"] if checks else ""
        completed_runs = [row for row in run_rows if row["status"] == "completed"]
        latest_run = run_rows[-1] if run_rows else None

        if error:
            status = "needs_review"
            message = f"影子跟踪回测失败：{error}"
        elif consecutive >= REQUIRED_MATCHED_TRADES:
            status = "verified"
            message = f"已连续对齐 {consecutive} 笔交易，策略通过实盘一致性跟踪。"
        elif latest_check_status == "failed":
            status = "needs_review"
            message = "最近一笔影子回测与实盘/纸面交易不一致，需要人工查看差异。"
        elif pending_checks > 0:
            status = "waiting_for_live_data"
            message = "影子回测已生成，等待实盘交易记录用于对账。"
        else:
            status = "shadow_verifying"
            message = f"已对齐 {consecutive}/{REQUIRED_MATCHED_TRADES} 笔，继续生成跟踪回测。"

        return {
            "status": status,
            "required_matches": REQUIRED_MATCHED_TRADES,
            "matched_trades": min(consecutive, REQUIRED_MATCHED_TRADES),
            "consecutive_matches": consecutive,
            "total_checks": len(checks),
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "pending_checks": pending_checks,
            "shadow_runs": len(completed_runs),
            "last_shadow_date": latest_run["shadow_date"] if latest_run else None,
            "last_shadow_run_id": latest_run["id"] if latest_run else None,
            "last_data_mode": latest_run["data_mode"] if latest_run else None,
            "last_run_at": latest_run["finished_at"] if latest_run else None,
            "last_message": message,
            "package_hash": package.get("package_hash"),
        }

    def _initial_runtime_state(
        self,
        result: dict[str, Any],
        signal_set: dict[str, Any],
        verification: dict[str, Any],
    ) -> dict[str, Any]:
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        signal_summary = signal_set.get("summary") if isinstance(signal_set.get("summary"), dict) else {}
        return {
            "current_positions": [],
            "pending_candidates": [],
            "recent_signals": [],
            "closed_trades": [],
            "skip_events": [],
            "risk_events": [],
            "scan": {
                "last_scan_at": None,
                "next_scan_at": None,
                "last_signal_time": signal_summary.get("last_signal_time"),
                "source_event_count": signal_summary.get("event_count", 0),
            },
            "counters": {
                "today_signals": 0,
                "pending_candidates": 0,
                "open_positions": 0,
                "closed_trades": 0,
                "today_pnl": 0,
                "source_backtest_trades": summary.get("total_trades", 0),
                "shadow_runs": verification.get("shadow_runs", 0),
                "reconcile_passed": verification.get("passed_checks", 0),
                "reconcile_failed": verification.get("failed_checks", 0),
            },
        }

    def _refresh_runtime_state(
        self,
        strategy_id: str,
        strategy: dict[str, Any],
        result: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        previous = strategy.get("runtime_state") if isinstance(strategy.get("runtime_state"), dict) else {}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source, pnl_usdt, payload, created_at
                FROM live_trade_records
                WHERE strategy_id = ?
                ORDER BY sequence_no DESC, created_at DESC
                LIMIT 30
                """,
                (strategy_id,),
            ).fetchall()
            check_counts = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM live_reconcile_checks
                WHERE strategy_id = ?
                GROUP BY status
                """,
                (strategy_id,),
            ).fetchall()
            shadow_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM live_shadow_runs
                WHERE strategy_id = ? AND status = ?
                """,
                (strategy_id, "completed"),
            ).fetchone()
        live_rows = [row for row in rows if row["source"] in {"paper_live", "manual_live", "exchange_live"}]
        shadow_rows = [row for row in rows if row["source"] == "shadow_backtest"]
        recent_live = [_loads_json(row["payload"], {}) for row in live_rows[:10]]
        recent_shadow = [_loads_json(row["payload"], {}) for row in shadow_rows[:10]]
        counts = {row["status"]: int(row["count"] or 0) for row in check_counts}
        trades = result.get("trades") if isinstance(result.get("trades"), list) else []
        today_pnl = sum(float(row["pnl_usdt"] or 0) for row in live_rows)
        now = _now_ms()
        return {
            **previous,
            "current_positions": [],
            "pending_candidates": [],
            "recent_signals": [
                {
                    "inst_id": event.get("inst_id"),
                    "time": event.get("confirm_time") or event.get("signal_time"),
                    "reason": "跟踪异动",
                    "strength": event.get("strength"),
                }
                for event in events[-10:]
            ],
            "closed_trades": recent_live,
            "shadow_trades": recent_shadow,
            "skip_events": [],
            "risk_events": [],
            "scan": {
                **(previous.get("scan") if isinstance(previous.get("scan"), dict) else {}),
                "last_scan_at": now,
                "next_scan_at": None,
                "last_signal_time": events[-1].get("confirm_time") if events else None,
                "source_event_count": len(events),
            },
            "counters": {
                **(previous.get("counters") if isinstance(previous.get("counters"), dict) else {}),
                "today_signals": len(events),
                "pending_candidates": 0,
                "open_positions": 0,
                "closed_trades": len(live_rows),
                "today_pnl": round(today_pnl, 4),
                "shadow_trades": len(trades),
                "shadow_runs": int(shadow_count["count"] or 0) if shadow_count else 0,
                "reconcile_passed": counts.get("passed", 0),
                "reconcile_failed": counts.get("failed", 0),
                "reconcile_pending": counts.get("pending", 0),
            },
        }

    def _normalize_mode(self, mode: Any) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized not in SUPPORTED_MODES:
            raise ValueError(f"不支持的实盘模式：{mode}")
        return normalized

    def _normalize_refresh_mode(self, mode: Any) -> str:
        normalized = str(mode or "incremental").strip().lower()
        if normalized not in SUPPORTED_REFRESH_MODES:
            raise ValueError(f"不支持的回测更新模式：{mode}")
        return normalized

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_strategies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_backtest_id TEXT NOT NULL,
                    source_signal_set_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    strategy_package TEXT NOT NULL,
                    consistency_check TEXT NOT NULL,
                    verification_state TEXT NOT NULL DEFAULT '{}',
                    runtime_state TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    started_at INTEGER,
                    paused_at INTEGER,
                    stopped_at INTEGER
                )
                """
            )
            self._ensure_column(conn, "live_strategies", "verification_state", "TEXT NOT NULL DEFAULT '{}'")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_strategies_updated_at
                ON live_strategies(updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_strategies_source_backtest
                ON live_strategies(source_backtest_id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_shadow_runs (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    shadow_date TEXT NOT NULL,
                    data_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    signal_summary TEXT NOT NULL,
                    result TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    finished_at INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_shadow_runs_strategy
                ON live_shadow_runs(strategy_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_trade_records (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    shadow_run_id TEXT,
                    source TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    trade_key TEXT NOT NULL,
                    inst_id TEXT NOT NULL,
                    side TEXT,
                    status TEXT NOT NULL,
                    signal_ts INTEGER,
                    confirm_ts INTEGER,
                    entry_ts INTEGER,
                    exit_ts INTEGER,
                    entry_price REAL,
                    exit_price REAL,
                    pnl_usdt REAL,
                    payload TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_trade_records_strategy
                ON live_trade_records(strategy_id, sequence_no ASC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_reconcile_checks (
                    id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    shadow_trade_id TEXT NOT NULL,
                    live_trade_id TEXT,
                    sequence_no INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    mismatches TEXT NOT NULL,
                    tolerance TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_reconcile_strategy
                ON live_reconcile_checks(strategy_id, sequence_no ASC)
                """
            )

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(row["name"] == column for row in rows):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _row_to_item(self, row: sqlite3.Row, *, compact: bool) -> dict[str, Any]:
        package = _loads_json(row["strategy_package"], {})
        if isinstance(package, dict):
            package = self._hydrated_strategy_package(
                {
                    "id": row["id"],
                    "source_signal_set_id": row["source_signal_set_id"],
                },
                package,
            )
        verification = _loads_json(row["verification_state"], {})
        if not verification:
            verification = _verification_from_compat(_loads_json(row["consistency_check"], {}), package)
        compatibility = _verification_to_compat_check(verification, package)
        runtime = _loads_json(row["runtime_state"], {})
        if compact and isinstance(runtime, dict):
            runtime = {
                "scan": runtime.get("scan", {}),
                "counters": runtime.get("counters", {}),
                "current_positions": runtime.get("current_positions", []),
                "pending_candidates": runtime.get("pending_candidates", []),
                "closed_trades": runtime.get("closed_trades", [])[:5],
                "shadow_trades": runtime.get("shadow_trades", [])[:5],
            }
        strategy_id = row["id"]
        return {
            "id": strategy_id,
            "name": row["name"],
            "source_backtest_id": row["source_backtest_id"],
            "source_signal_set_id": row["source_signal_set_id"],
            "mode": row["mode"],
            "status": row["status"],
            "strategy_package": package,
            "verification_state": verification,
            "consistency_check": compatibility,
            "runtime_state": runtime,
            "lifecycle": self._lifecycle_view(strategy_id, row, package, compact=compact),
            "shadow_runs": self._shadow_runs(strategy_id, limit=3 if compact else 20),
            "reconcile_checks": self._reconcile_checks(strategy_id, limit=5 if compact else 30),
            "live_trades": self._trade_records(strategy_id, sources=("paper_live", "manual_live", "exchange_live"), limit=5 if compact else 30),
            "shadow_trades": self._trade_records(strategy_id, sources=("shadow_backtest",), limit=5 if compact else 30),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "paused_at": row["paused_at"],
            "stopped_at": row["stopped_at"],
        }

    def _lifecycle_view(
        self,
        strategy_id: str,
        row: sqlite3.Row,
        package: dict[str, Any],
        *,
        compact: bool,
    ) -> dict[str, Any]:
        backtest = backtest_service.get_run(str(row["source_backtest_id"] or ""))
        runtime = _loads_json(row["runtime_state"], {})
        refreshed = runtime.get("refreshed_backtest") if isinstance(runtime.get("refreshed_backtest"), dict) else {}
        refreshed_result = refreshed.get("result") if isinstance(refreshed.get("result"), dict) else None
        result = refreshed_result if refreshed_result else backtest.get("result") if isinstance(backtest, dict) and isinstance(backtest.get("result"), dict) else {}
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        source_curve = result.get("daily_equity") if isinstance(result.get("daily_equity"), list) else []
        if not source_curve:
            source_curve = result.get("equity") if isinstance(result.get("equity"), list) else []
        source_trades = result.get("trades") if isinstance(result.get("trades"), list) else []
        checkpoints = result.get("checkpoints") if isinstance(result.get("checkpoints"), list) else []

        marker_date = str((package.get("signal") or {}).get("end_date") or summary.get("end_date") or _date_from_ms(row["created_at"]))
        initial_capital = _safe_float(summary.get("initial_capital"))
        if initial_capital is None or initial_capital <= 0:
            initial_capital = _first_equity(source_curve) or 1.0
        marker_equity = _equity_at_or_before(source_curve, marker_date) or _last_equity(source_curve) or initial_capital

        details: dict[str, dict[str, Any]] = {}
        for trade in source_trades:
            item_date = _trade_date(trade)
            if not item_date:
                continue
            detail = _detail_for_date(details, item_date)
            detail["backtest_trades"].append(trade)

        for checkpoint in checkpoints:
            item_date = str(checkpoint.get("date") or (str(checkpoint.get("signal_time") or "")[:10]))
            if not item_date:
                continue
            detail = _detail_for_date(details, item_date)
            detail["signal_count"] += int(checkpoint.get("matched_count") or 0)
            detail["opened_count"] += int(checkpoint.get("opened_count") or 0)

        shadow_records = self._trade_records(strategy_id, sources=("shadow_backtest",), limit=10000)
        live_records = self._trade_records(strategy_id, sources=("paper_live", "manual_live", "exchange_live"), limit=10000)
        reconcile_checks = self._reconcile_checks(strategy_id, limit=10000)
        shadow_runs = self._shadow_runs(strategy_id, limit=10000)

        for record in shadow_records:
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            item_date = _trade_settle_date(payload) or _date_from_ms(record.get("created_at"))
            detail = _detail_for_date(details, item_date)
            detail["shadow_trades"].append(record)
        for record in live_records:
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            item_date = _trade_settle_date(payload) or _date_from_ms(record.get("created_at"))
            detail = _detail_for_date(details, item_date)
            detail["live_trades"].append(record)
        for check in reconcile_checks:
            shadow_record = next((item for item in shadow_records if item["id"] == check.get("shadow_trade_id")), None)
            payload = shadow_record.get("payload") if shadow_record and isinstance(shadow_record.get("payload"), dict) else {}
            item_date = _trade_settle_date(payload) or _date_from_ms(check.get("created_at"))
            detail = _detail_for_date(details, item_date)
            detail["reconcile_checks"].append(check)
        for run in shadow_runs:
            item_date = str(run.get("shadow_date") or "")
            if not item_date:
                continue
            detail = _detail_for_date(details, item_date)
            signal_summary = run.get("signal_summary") if isinstance(run.get("signal_summary"), dict) else {}
            detail["signal_count"] += int(signal_summary.get("event_count") or signal_summary.get("matched_count") or 0)
            detail["shadow_runs"].append(run)

        curve = self._build_lifecycle_curve(
            source_curve=source_curve,
            details=details,
            marker_date=marker_date,
            initial_capital=initial_capital,
            marker_equity=marker_equity,
        )
        if compact and len(curve) > 160:
            curve = [*curve[:80], *curve[-80:]]

        detail_items = []
        for item_date in sorted(details):
            detail = details[item_date]
            detail_items.append(
                {
                    "date": item_date,
                    "signal_count": detail["signal_count"],
                    "opened_count": detail["opened_count"],
                    "backtest_trades": detail["backtest_trades"][:300],
                    "shadow_trades": detail["shadow_trades"][:300],
                    "live_trades": detail["live_trades"][:300],
                    "reconcile_checks": detail["reconcile_checks"][:300],
                    "shadow_runs": detail["shadow_runs"][:20],
                }
            )
        if compact:
            detail_items = detail_items[-10:]

        latest = curve[-1] if curve else None
        live_points = [item for item in curve if item.get("phase") == "live"]
        return {
            "marker": {
                "date": marker_date,
                "label": "实盘开启",
                "created_at": row["created_at"],
                "created_time": _date_from_ms(row["created_at"]),
                "equity": round(marker_equity, 4),
            },
            "summary": {
                "history_days": sum(1 for item in curve if item.get("phase") == "backtest"),
                "live_days": len(live_points),
                "latest_date": latest.get("date") if latest else None,
                "latest_backtest_return_pct": latest.get("backtest_return_pct") if latest else None,
                "latest_shadow_return_pct": latest.get("shadow_return_pct") if latest else None,
                "latest_live_return_pct": latest.get("live_return_pct") if latest else None,
            },
            "curve": curve,
            "daily_details": detail_items,
        }

    def _build_lifecycle_curve(
        self,
        *,
        source_curve: list[Any],
        details: dict[str, dict[str, Any]],
        marker_date: str,
        initial_capital: float,
        marker_equity: float,
    ) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        previous_equity: float | None = None
        for raw in source_curve:
            if not isinstance(raw, dict):
                continue
            item_date = _point_date(raw)
            equity = _safe_float(raw.get("equity"))
            if not item_date or equity is None:
                continue
            daily_pnl = equity - previous_equity if previous_equity is not None else 0.0
            daily_return_pct = daily_pnl / previous_equity * 100 if previous_equity else 0.0
            detail = details.get(item_date, {})
            points.append(
                {
                    "date": item_date,
                    "phase": "backtest",
                    "backtest_equity": round(equity, 4),
                    "backtest_return_pct": round((equity / initial_capital - 1) * 100, 4),
                    "daily_pnl": round(daily_pnl, 4),
                    "daily_return_pct": round(daily_return_pct, 4),
                    "drawdown_pct": raw.get("drawdown_pct", 0),
                    "trade_count": len(detail.get("backtest_trades", [])),
                    "signal_count": int(detail.get("signal_count") or 0),
                    "marker_event": "实盘开启" if item_date == marker_date else None,
                }
            )
            previous_equity = equity

        if marker_date and not any(item["date"] == marker_date for item in points):
            points.append(
                {
                    "date": marker_date,
                    "phase": "marker",
                    "backtest_equity": round(marker_equity, 4),
                    "backtest_return_pct": round((marker_equity / initial_capital - 1) * 100, 4),
                    "shadow_equity": round(marker_equity, 4),
                    "live_equity": round(marker_equity, 4),
                    "shadow_return_pct": 0,
                    "live_return_pct": 0,
                    "daily_pnl": 0,
                    "daily_return_pct": 0,
                    "trade_count": 0,
                    "signal_count": 0,
                    "marker_event": "实盘开启",
                }
            )

        shadow_daily = _daily_pnl_from_details(details, "shadow_trades")
        live_daily = _daily_pnl_from_details(details, "live_trades")
        post_dates = sorted({item for item in {*shadow_daily.keys(), *live_daily.keys(), *details.keys()} if item > marker_date})
        shadow_equity = marker_equity
        live_equity = marker_equity
        for item_date in post_dates:
            detail = details.get(item_date, {})
            shadow_pnl = shadow_daily.get(item_date, 0.0)
            live_pnl = live_daily.get(item_date, 0.0)
            shadow_equity += shadow_pnl
            live_equity += live_pnl
            points.append(
                {
                    "date": item_date,
                    "phase": "live",
                    "shadow_equity": round(shadow_equity, 4),
                    "live_equity": round(live_equity, 4),
                    "shadow_daily_pnl": round(shadow_pnl, 4),
                    "live_daily_pnl": round(live_pnl, 4),
                    "shadow_return_pct": round((shadow_equity / marker_equity - 1) * 100, 4) if marker_equity else 0,
                    "live_return_pct": round((live_equity / marker_equity - 1) * 100, 4) if marker_equity else 0,
                    "trade_count": len(detail.get("live_trades", [])) or len(detail.get("shadow_trades", [])),
                    "signal_count": int(detail.get("signal_count") or 0),
                    "reconcile_passed": sum(1 for item in detail.get("reconcile_checks", []) if item.get("status") == "passed"),
                    "reconcile_failed": sum(1 for item in detail.get("reconcile_checks", []) if item.get("status") == "failed"),
                    "marker_event": None,
                }
            )
        points.sort(key=lambda item: str(item.get("date") or ""))
        return points

    def _shadow_runs(self, strategy_id: str, *, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, shadow_date, data_mode, status, signal_summary, result,
                       error, created_at, finished_at
                FROM live_shadow_runs
                WHERE strategy_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (strategy_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            result = _loads_json(row["result"], {})
            summary = result.get("summary") if isinstance(result, dict) else {}
            items.append(
                {
                    "id": row["id"],
                    "shadow_date": row["shadow_date"],
                    "data_mode": row["data_mode"],
                    "status": row["status"],
                    "signal_summary": _loads_json(row["signal_summary"], {}),
                    "summary": summary if isinstance(summary, dict) else {},
                    "error": row["error"],
                    "created_at": row["created_at"],
                    "finished_at": row["finished_at"],
                }
            )
        return items

    def _trade_records(self, strategy_id: str, *, sources: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in sources)
        params: tuple[Any, ...] = (strategy_id, *sources, limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, shadow_run_id, source, sequence_no, trade_key, inst_id,
                       side, status, signal_ts, confirm_ts, entry_ts, exit_ts,
                       entry_price, exit_price, pnl_usdt, payload, created_at
                FROM live_trade_records
                WHERE strategy_id = ? AND source IN ({placeholders})
                ORDER BY sequence_no DESC, created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": row["id"],
                "shadow_run_id": row["shadow_run_id"],
                "source": row["source"],
                "sequence_no": row["sequence_no"],
                "trade_key": row["trade_key"],
                "inst_id": row["inst_id"],
                "side": row["side"],
                "status": row["status"],
                "signal_ts": row["signal_ts"],
                "confirm_ts": row["confirm_ts"],
                "entry_ts": row["entry_ts"],
                "exit_ts": row["exit_ts"],
                "entry_price": row["entry_price"],
                "exit_price": row["exit_price"],
                "pnl_usdt": row["pnl_usdt"],
                "payload": _loads_json(row["payload"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _reconcile_checks(self, strategy_id: str, *, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, shadow_trade_id, live_trade_id, sequence_no, status,
                       mismatches, tolerance, created_at
                FROM live_reconcile_checks
                WHERE strategy_id = ?
                ORDER BY sequence_no DESC, created_at DESC
                LIMIT ?
                """,
                (strategy_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "shadow_trade_id": row["shadow_trade_id"],
                "live_trade_id": row["live_trade_id"],
                "sequence_no": row["sequence_no"],
                "status": row["status"],
                "mismatches": _loads_json(row["mismatches"], []),
                "tolerance": _loads_json(row["tolerance"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _hash_payload(payload: Any) -> str:
    raw = _dump_json(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _status_change_reason(status: str) -> str:
    return {
        "running": "用户启动策略跟踪",
        "paused": "用户暂停策略跟踪",
        "stopped": "用户停止策略跟踪",
        "tripped": "用户触发手动熔断",
    }.get(status, "状态变更")


def _trade_key(strategy_id: str, source: str, sequence_no: int, trade: dict[str, Any]) -> str:
    payload = {
        "strategy_id": strategy_id,
        "source": source,
        "sequence_no": sequence_no,
        "inst_id": trade.get("inst_id"),
        "confirm_ts": trade.get("confirm_ts"),
        "entry_ts": trade.get("entry_ts"),
        "exit_ts": trade.get("exit_ts"),
    }
    return _hash_payload(payload)


def _compare_trade_payloads(
    shadow: dict[str, Any],
    live: dict[str, Any],
    tolerance: dict[str, float],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    exact_fields = ("inst_id", "side", "confirm_ts", "entry_ts", "exit_ts", "exit_reason")
    for field in exact_fields:
        if shadow.get(field) != live.get(field):
            mismatches.append({"field": field, "shadow": shadow.get(field), "live": live.get(field)})

    for field in ("entry_price", "exit_price"):
        left = _safe_float(shadow.get(field) if shadow.get(field) is not None else shadow.get(f"raw_{field}"))
        right = _safe_float(live.get(field) if live.get(field) is not None else live.get(f"raw_{field}"))
        if not _within_pct(left, right, float(tolerance.get("price_pct") or 0)):
            mismatches.append({"field": field, "shadow": left, "live": right})

    left_pnl = _safe_float(shadow.get("pnl_usdt"))
    right_pnl = _safe_float(live.get("pnl_usdt"))
    if left_pnl is None or right_pnl is None or abs(left_pnl - right_pnl) > float(tolerance.get("pnl_usdt") or 0):
        mismatches.append({"field": "pnl_usdt", "shadow": left_pnl, "live": right_pnl})

    return mismatches


def _within_pct(left: float | None, right: float | None, tolerance_pct: float) -> bool:
    if left is None or right is None:
        return left == right
    if left == right:
        return True
    base = abs(left) if abs(left) > 1e-12 else 1.0
    return abs(left - right) / base * 100 <= tolerance_pct


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_from_ms(value: Any) -> str:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        millis = _now_ms()
    return datetime.fromtimestamp(millis / 1000, tz=APP_TZ).date().isoformat()


def _next_date(value: str) -> str:
    try:
        return (Date.fromisoformat(value) + timedelta(days=1)).isoformat()
    except ValueError:
        return value


def _date_start_ms(value: str) -> int:
    try:
        dt = datetime.fromisoformat(f"{value}T00:00:00").replace(tzinfo=APP_TZ)
    except ValueError:
        return 0
    return int(dt.timestamp() * 1000)


def _timeframe_minutes(value: str) -> int | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    unit = normalized[-1]
    try:
        count = int(normalized[:-1])
    except ValueError:
        return None
    if count <= 0:
        return None
    if unit == "m":
        return count
    if unit == "h":
        return count * 60
    if unit == "d":
        return count * 24 * 60
    return None


def _renumber_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_trades = sorted(
        trades,
        key=lambda item: (
            _safe_int(item.get("exit_ts")) or 0,
            _safe_int(item.get("entry_ts")) or 0,
            str(item.get("inst_id") or ""),
        ),
    )
    return [{**trade, "id": index} for index, trade in enumerate(sorted_trades, start=1)]


def _point_date(point: dict[str, Any]) -> str:
    text = str(point.get("time") or "")
    if len(text) >= 10:
        return text[:10]
    ts = point.get("ts")
    if ts:
        return _date_from_ms(ts)
    return ""


def _trade_date(trade: dict[str, Any]) -> str:
    for key in ("exit_time", "entry_time", "confirm_time", "signal_time", "time"):
        text = str(trade.get(key) or "")
        if len(text) >= 10:
            return text[:10]
    for key in ("exit_ts", "entry_ts", "confirm_ts", "signal_ts", "ts"):
        value = trade.get(key)
        if value:
            return _date_from_ms(value)
    return ""


def _trade_settle_date(trade: dict[str, Any]) -> str:
    for key in ("exit_time", "entry_time", "confirm_time", "signal_time", "time"):
        text = str(trade.get(key) or "")
        if len(text) >= 10:
            return text[:10]
    for key in ("exit_ts", "entry_ts", "confirm_ts", "signal_ts", "ts"):
        value = trade.get(key)
        if value:
            return _date_from_ms(value)
    return ""


def _detail_for_date(details: dict[str, dict[str, Any]], item_date: str) -> dict[str, Any]:
    return details.setdefault(
        item_date,
        {
            "signal_count": 0,
            "opened_count": 0,
            "backtest_trades": [],
            "shadow_trades": [],
            "live_trades": [],
            "reconcile_checks": [],
            "shadow_runs": [],
        },
    )


def _first_equity(points: list[Any]) -> float | None:
    for point in points:
        if isinstance(point, dict):
            value = _safe_float(point.get("equity"))
            if value is not None:
                return value
    return None


def _last_equity(points: list[Any]) -> float | None:
    for point in reversed(points):
        if isinstance(point, dict):
            value = _safe_float(point.get("equity"))
            if value is not None:
                return value
    return None


def _equity_at_or_before(points: list[Any], item_date: str) -> float | None:
    selected: float | None = None
    for point in points:
        if not isinstance(point, dict):
            continue
        point_date = _point_date(point)
        if point_date and point_date <= item_date:
            value = _safe_float(point.get("equity"))
            if value is not None:
                selected = value
    return selected


def _daily_pnl_from_details(details: dict[str, dict[str, Any]], key: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for item_date, detail in details.items():
        total = 0.0
        for record in detail.get(key, []):
            payload = record.get("payload") if isinstance(record, dict) and isinstance(record.get("payload"), dict) else record
            pnl = _safe_float(payload.get("pnl_usdt") if isinstance(payload, dict) else None)
            if pnl is not None:
                total += pnl
        if total:
            values[item_date] = total
    return values


def _verification_to_compat_check(verification: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    status = str(verification.get("status") or "shadow_verifying")
    compat_status = "passed" if status == "verified" else "failed" if status == "needs_review" else "pending"
    matched = int(verification.get("matched_trades") or 0)
    required = int(verification.get("required_matches") or REQUIRED_MATCHED_TRADES)
    checks = [
        {
            "key": "package_frozen",
            "label": "策略包已冻结",
            "passed": bool(package.get("package_hash")),
            "detail": str(package.get("package_hash") or ""),
        },
        {
            "key": "shadow_runs",
            "label": "跟踪回测已生成",
            "passed": int(verification.get("shadow_runs") or 0) > 0,
            "detail": f"{verification.get('shadow_runs') or 0} 轮",
        },
        {
            "key": "trade_reconcile",
            "label": "三笔动态对账",
            "passed": matched >= required,
            "detail": f"{matched}/{required}",
        },
    ]
    return {
        "status": compat_status,
        "checked_at": verification.get("last_run_at") or _now_ms(),
        "engine_version": LIVE_ENGINE_VERSION,
        "message": verification.get("last_message") or "",
        "checks": checks,
    }


def _verification_from_compat(compat: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    compat_status = str(compat.get("status") or "")
    status = "verified" if compat_status == "passed" else "shadow_verifying"
    message = (
        "旧策略已迁移为影子验证流程，等待生成每日跟踪回测。"
        if status != "verified"
        else "旧策略已迁移为已验证状态。"
    )
    return {
        "status": status,
        "required_matches": REQUIRED_MATCHED_TRADES,
        "matched_trades": REQUIRED_MATCHED_TRADES if status == "verified" else 0,
        "consecutive_matches": REQUIRED_MATCHED_TRADES if status == "verified" else 0,
        "total_checks": 0,
        "passed_checks": 0,
        "failed_checks": 0,
        "pending_checks": 0,
        "shadow_runs": 0,
        "last_shadow_date": None,
        "last_shadow_run_id": None,
        "last_run_at": compat.get("checked_at"),
        "last_message": message,
        "package_hash": package.get("package_hash"),
    }


live_strategy_service = LiveStrategyService()
