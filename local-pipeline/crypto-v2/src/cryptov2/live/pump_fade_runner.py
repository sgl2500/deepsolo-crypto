from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cryptov2.data.ticker_snapshot import TickerSnapshotStore
from cryptov2.data.schemas import CST, HOUR_MS
from cryptov2.live.pump_fade_market import PumpFadeMarketData
from cryptov2.live.pump_fade_state import PumpFadeStateStore
from cryptov2.strategies.pump_fade.bot_compat import (
    filter_bot_signal_candidates,
    find_bot_entry,
    scan_bot_signals,
)
from cryptov2.strategies.pump_fade.config import PumpFadeConfig


@dataclass(frozen=True, slots=True)
class PumpFadeLiveRunnerConfig:
    dry_run: bool = True
    max_workers: int = 10
    scan_1h_limit: int = 5
    entry_5m_limit: int = 12


class PumpFadeLiveRunner:
    """Old bot compatible pump_fade live loop.

    This runner intentionally supports dry-run/paper state first. Real trading
    should be wired only after broker reconciliation and exchange stop-loss are
    in place.
    """

    def __init__(
        self,
        market: PumpFadeMarketData,
        state: PumpFadeStateStore,
        strategy_config: PumpFadeConfig,
        runner_config: PumpFadeLiveRunnerConfig | None = None,
        ticker_snapshots: TickerSnapshotStore | None = None,
    ):
        self.market = market
        self.state = state
        self.strategy_config = strategy_config
        self.runner_config = runner_config or PumpFadeLiveRunnerConfig()
        self.ticker_snapshots = ticker_snapshots

    def healthcheck(self) -> dict[str, Any]:
        positions = self.state.load_positions()
        active_positions = sum(1 for pos in positions.values() if pos.get("status") == "active")
        closed_positions = sum(1 for pos in positions.values() if pos.get("status") == "closed")
        return {
            "dry_run": self.runner_config.dry_run,
            "state_root": str(self.state.root),
            "watchlist": len(self.state.load_watchlist()),
            "active_positions": active_positions,
            "closed_positions": closed_positions,
        }

    def run_cycle(self, now: datetime | None = None, force_scan: bool = False) -> dict[str, Any]:
        now = now or datetime.now(CST)
        now_ts = int(now.timestamp() * 1000)
        is_hourly = now.minute == 0 or force_scan

        if is_hourly:
            watchlist = self.scan_watchlist(now_ts)
            self.state.save_watchlist(watchlist)
        else:
            watchlist = self.state.load_watchlist()

        opened = self.check_entries(watchlist, now, now_ts)
        closed = self.manage_positions(now, now_ts)
        positions = self.state.load_positions()
        active_positions = sum(1 for pos in positions.values() if pos.get("status") == "active")
        return {
            "now": now.isoformat(),
            "scanned": is_hourly,
            "watchlist": len(watchlist),
            "opened": opened,
            "closed": closed,
            "active_positions": active_positions,
        }

    def scan_watchlist(self, now_ts: int) -> list[dict[str, Any]]:
        tickers = self.market.get_tickers()
        if self.ticker_snapshots is not None:
            self.ticker_snapshots.write_snapshot(now_ts, tickers, source="live_scan")
        candidates = filter_bot_signal_candidates(tickers, self.strategy_config)
        bars_1h = self.market.get_bars_batch(
            candidates,
            "1H",
            self.runner_config.scan_1h_limit,
            self.runner_config.max_workers,
        )
        return [
            signal.to_state_dict()
            for signal in scan_bot_signals(tickers, bars_1h, self.strategy_config, now_ts)
        ]

    def check_entries(self, watchlist: list[dict[str, Any]], now: datetime, now_ts: int) -> int:
        positions = self.state.load_positions()
        active_ids = {
            inst_id for inst_id, pos in positions.items() if pos.get("status") == "active"
        }
        opened = 0
        for signal in watchlist:
            inst_id = signal.get("inst_id")
            confirm_ts = int(signal.get("confirm_ts") or 0)
            if not inst_id or not confirm_ts or inst_id in active_ids:
                continue
            elapsed_min = (now_ts - confirm_ts) / 60_000
            if elapsed_min > self.strategy_config.entry_search_window_min:
                continue
            bars_5m = self.market.get_bars(inst_id, "5m", self.runner_config.entry_5m_limit)
            entry = find_bot_entry(
                bars_5m,
                confirm_ts,
                self.strategy_config,
                now_ts=now_ts,
                enforce_stale_guard=True,
            )
            if entry is None:
                continue
            if self.open_position(inst_id, entry.to_state_dict(), signal, now):
                active_ids.add(inst_id)
                opened += 1
        return opened

    def open_position(
        self,
        inst_id: str,
        entry_info: dict[str, Any],
        signal_info: dict[str, Any],
        now: datetime,
    ) -> bool:
        positions = self.state.load_positions()
        active_count = sum(1 for pos in positions.values() if pos.get("status") == "active")
        if active_count >= self.strategy_config.max_positions:
            return False
        if inst_id in positions and positions[inst_id].get("status") == "active":
            return False
        if not self.runner_config.dry_run:
            raise RuntimeError("real trading broker is not wired in crypto-v2 yet")

        margin = self.strategy_config.capital_per_trade_usd
        leverage = self.strategy_config.leverage
        contracts = 0
        entry_ts = int(entry_info["entry_ts"])
        exit_ts = (entry_ts // HOUR_MS + 2) * HOUR_MS
        exit_time = datetime.fromtimestamp(exit_ts / 1000, tz=CST)
        positions[inst_id] = {
            "status": "active",
            "side": "short",
            "entry_time": now.isoformat(),
            "entry_price": float(entry_info["entry_price"]),
            "entry_ts": entry_ts,
            "exit_ts": exit_ts,
            "exit_time": exit_time.isoformat(),
            "contracts": contracts,
            "leverage": leverage,
            "margin_usd": margin,
            "signal_gain": signal_info.get("cum_gain", 0),
            "signal_time": signal_info.get("confirm_time", ""),
            "trigger": entry_info.get("trigger", []),
            "delay_min": entry_info.get("delay_min", 0),
            "current_pnl_pct": 0,
            "current_price": float(entry_info["entry_price"]),
            "max_adverse": 0,
        }
        self.state.save_positions(positions)
        self.state.append_trade({
            "time": now.isoformat(),
            "action": "open_short",
            "inst_id": inst_id,
            "price": float(entry_info["entry_price"]),
            "margin": margin,
            "leverage": leverage,
            "contracts": contracts,
            "signal_gain": signal_info.get("cum_gain", 0),
            "dry_run": self.runner_config.dry_run,
        })
        return True

    def manage_positions(self, now: datetime, now_ts: int) -> int:
        positions = self.state.load_positions()
        closed = 0
        for inst_id, pos in list(positions.items()):
            if pos.get("status") != "active":
                continue
            ticker = self.market.get_ticker(inst_id)
            if ticker is None:
                continue
            current_price = float(ticker.last)
            entry_price = float(pos["entry_price"])
            pnl_pct = -(current_price - entry_price) / entry_price * 100.0
            if -pnl_pct > float(pos.get("max_adverse", 0)):
                pos["max_adverse"] = round(-pnl_pct, 2)
            pos["current_pnl_pct"] = round(pnl_pct, 2)
            pos["current_price"] = current_price

            reason = None
            if pnl_pct <= -self.strategy_config.stop_loss_pct:
                reason = f"止损 (PnL={pnl_pct:+.2f}% <= -{self.strategy_config.stop_loss_pct}%)"
            elif pos.get("exit_ts") and now_ts >= int(pos["exit_ts"]):
                reason = f"到期平仓 (PnL={pnl_pct:+.2f}%)"
            if not reason:
                continue
            if not self.runner_config.dry_run:
                raise RuntimeError("real trading broker is not wired in crypto-v2 yet")

            pnl_usd = (
                pos["current_pnl_pct"]
                / 100.0
                * float(pos["margin_usd"])
                * float(pos["leverage"])
            )
            pos["status"] = "closed"
            pos["close_time"] = now.isoformat()
            pos["close_price"] = current_price
            pos["close_pnl_pct"] = pos["current_pnl_pct"]
            pos["close_pnl_usd"] = round(pnl_usd, 2)
            pos["close_reason"] = reason
            self.state.append_trade({
                "time": now.isoformat(),
                "action": "close_short",
                "inst_id": inst_id,
                "price": current_price,
                "pnl_pct": pos["current_pnl_pct"],
                "pnl_usd": round(pnl_usd, 2),
                "reason": reason,
                "dry_run": self.runner_config.dry_run,
            })
            closed += 1
        self.state.save_positions(positions)
        return closed
