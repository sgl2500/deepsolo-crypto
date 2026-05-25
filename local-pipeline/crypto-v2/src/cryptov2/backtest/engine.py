from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Protocol

from cryptov2.data.schemas import HOUR_MS, Bar, BarSize, Position, StopModel, short_pnl_pct
from cryptov2.strategies.base import StrategyContext
from cryptov2.strategies.pump_fade.config import PumpFadeConfig
from cryptov2.strategies.pump_fade.strategy import PumpFadeStrategy


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    klines_dir: str
    signal_source: str = "aggregate_5m"
    stop_model: StopModel = StopModel.HARD_INTRABAR


@dataclass(slots=True)
class BacktestResult:
    positions: list[Position]
    raw_signal_count: int
    raw_order_count: int
    scanned_symbols: int


class KlineProvider(Protocol):
    root: object

    def symbols(self, bar: BarSize = "5m") -> list[str]: ...
    def load_bars(self, inst_id: str, bar: BarSize) -> list[Bar]: ...
    def load_1h_from_5m(self, inst_id: str) -> list[Bar]: ...


class BacktestEngine:
    def __init__(self, provider: KlineProvider, strategy: PumpFadeStrategy, config: BacktestConfig):
        self.provider = provider
        self.strategy = strategy
        self.config = config
        self.strategy_config: PumpFadeConfig = strategy.config

    def run(self) -> BacktestResult:
        orders = []
        raw_signal_count = 0
        scanned_symbols = 0
        for inst_id in self.provider.symbols("5m"):
            bars_5m = self.provider.load_bars(inst_id, "5m")
            if self.config.signal_source == "aggregate_5m":
                bars_1h = self.provider.load_1h_from_5m(inst_id)
            else:
                bars_1h = self.provider.load_bars(inst_id, "1H")
            if len(bars_1h) < 3 or len(bars_5m) < 20:
                continue
            scanned_symbols += 1
            signals = self.strategy.prepare_symbol(inst_id, bars_1h, bars_5m)
            raw_signal_count += len(signals)
            for signal in signals:
                order = self.strategy.order_for_signal(
                    signal,
                    bars_5m,
                    StrategyContext(signal.confirm_ts, self.strategy_config.capital_per_trade_usd, {}),
                )
                if order:
                    orders.append((order.ts, inst_id, order, bars_5m))

        orders.sort(key=lambda item: (item[0], -item[2].attrs.get("signal_gain_pct", 0), item[1]))
        positions: list[Position] = []
        active: list[Position] = []
        for _, inst_id, order, bars_5m in orders:
            active = [pos for pos in active if pos.exit_ts is not None and pos.exit_ts > order.ts]
            if any(pos.inst_id == inst_id for pos in active):
                continue
            if len(active) >= self.strategy_config.max_positions:
                continue
            pos = self._simulate_position(order, bars_5m)
            if pos is None:
                continue
            positions.append(pos)
            active.append(pos)
        return BacktestResult(positions, raw_signal_count, len(orders), scanned_symbols)

    def _simulate_position(self, order, bars_5m: list[Bar]) -> Position | None:
        ts_list = [bar.ts for bar in bars_5m]
        entry_idx = bisect_left(ts_list, order.ts)
        if entry_idx >= len(bars_5m):
            return None
        entry_bar = bars_5m[entry_idx]
        entry_price = entry_bar.open
        scheduled_exit_ts = (entry_bar.ts // HOUR_MS + 2) * HOUR_MS
        scheduled_exit_idx = bisect_left(ts_list, scheduled_exit_ts)
        if scheduled_exit_idx >= len(bars_5m):
            return None

        stop_price = entry_price * (1.0 + self.strategy_config.stop_loss_pct / 100.0)
        exit_idx = scheduled_exit_idx
        exit_price = bars_5m[scheduled_exit_idx].open
        reason = "time"
        max_adverse = 0.0
        max_favorable = 0.0

        for idx in range(entry_idx, scheduled_exit_idx):
            bar = bars_5m[idx]
            max_adverse = max(max_adverse, (bar.high - entry_price) / entry_price * 100.0)
            max_favorable = max(max_favorable, -(bar.low - entry_price) / entry_price * 100.0)
            if self.config.stop_model == StopModel.HARD_INTRABAR and bar.high >= stop_price:
                exit_idx = idx
                exit_price = stop_price
                reason = StopModel.HARD_INTRABAR.value
                break
            if self.config.stop_model == StopModel.BOT_CHECKPOINT and idx > entry_idx and bar.open >= stop_price:
                exit_idx = idx
                exit_price = bar.open
                reason = StopModel.BOT_CHECKPOINT.value
                break

        exit_bar = bars_5m[exit_idx]
        max_adverse = max(max_adverse, (exit_bar.high - entry_price) / entry_price * 100.0)
        max_favorable = max(max_favorable, -(exit_bar.low - entry_price) / entry_price * 100.0)
        gross = short_pnl_pct(exit_price, entry_price)
        cost = 2.0 * (self.strategy_config.fee_bps_per_side + self.strategy_config.slippage_bps_per_side) / 100.0
        net = gross - cost
        return Position(
            strategy=order.strategy,
            inst_id=order.inst_id,
            side="short",
            entry_ts=entry_bar.ts,
            entry_price=entry_price,
            notional_usd=order.notional_usd,
            attrs=order.attrs,
            exit_ts=exit_bar.ts,
            exit_price=exit_price,
            gross_pnl_pct=round(gross, 4),
            net_pnl_pct=round(net, 4),
            reason=reason,
            max_adverse_pct=round(max_adverse, 4),
            max_favorable_pct=round(max_favorable, 4),
        )
