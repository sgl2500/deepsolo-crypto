from __future__ import annotations

from typing import Protocol

from cryptov2.data.schemas import Bar, HOUR_MS, OrderIntent, Signal
from cryptov2.strategies.base import Strategy, StrategyContext
from cryptov2.strategies.pump_fade.bot_compat import find_bot_entry
from cryptov2.strategies.pump_fade.config import PumpFadeConfig


class VolumeGate(Protocol):
    def volume_usdt(self, inst_id: str, ts_ms: int) -> float | None: ...


class PumpFadeStrategy(Strategy):
    name = "pump_fade_v1"

    def __init__(self, config: PumpFadeConfig, volume_gate: VolumeGate | None = None):
        self.config = config
        self.volume_gate = volume_gate

    def prepare_symbol(self, inst_id: str, bars_1h: list[Bar], bars_5m: list[Bar]) -> list[Signal]:
        del bars_5m
        signals: list[Signal] = []
        for idx in range(len(bars_1h) - 1):
            k1 = bars_1h[idx]
            k2 = bars_1h[idx + 1]
            if not (k1.is_green and k2.is_green and k1.open > 0):
                continue
            gain = (k2.close - k1.open) / k1.open * 100.0
            if gain < self.config.signal_min_gain_pct:
                continue
            confirm_ts = k2.ts + HOUR_MS
            quote_vol = self._signal_quote_volume(inst_id, confirm_ts, bars_1h, idx + 1)
            if quote_vol < self.config.signal_min_vol_usdt:
                continue
            signals.append(Signal(
                strategy=self.name,
                inst_id=inst_id,
                signal_ts=k2.ts,
                confirm_ts=confirm_ts,
                strength=round(gain, 4),
                attrs={
                    "signal_gain_pct": round(gain, 4),
                    "rolling_24h_quote_vol": round(quote_vol, 2),
                },
            ))
        return signals

    def order_for_signal(
        self,
        signal: Signal,
        bars_5m: list[Bar],
        context: StrategyContext,
    ) -> OrderIntent | None:
        if signal.inst_id in context.open_positions:
            return None
        entry = find_bot_entry(bars_5m, signal.confirm_ts, self.config)
        if entry is None:
            return None
        return OrderIntent(
            strategy=self.name,
            inst_id=signal.inst_id,
            side="sell",
            position_side="short",
            ts=entry.entry_ts,
            ref_price=entry.entry_price,
            notional_usd=self.config.capital_per_trade_usd * self.config.leverage,
            reason="pump_fade_entry",
            attrs={
                **signal.attrs,
                "delay_min": round(entry.delay_min, 1),
                "trigger": entry.trigger,
            },
        )

    @staticmethod
    def _rolling_quote_volume(bars_1h: list[Bar], end_idx: int) -> float:
        start = max(0, end_idx - 23)
        return sum(bar.vol_ccy * bar.close for bar in bars_1h[start:end_idx + 1])

    def _signal_quote_volume(
        self,
        inst_id: str,
        confirm_ts: int,
        bars_1h: list[Bar],
        end_idx: int,
    ) -> float:
        if self.volume_gate is not None:
            snapshot_volume = self.volume_gate.volume_usdt(inst_id, confirm_ts)
            if snapshot_volume is not None:
                return snapshot_volume
        return self._rolling_quote_volume(bars_1h, end_idx)
