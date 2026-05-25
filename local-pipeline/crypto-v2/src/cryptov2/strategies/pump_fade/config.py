from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PumpFadeConfig:
    capital_per_trade_usd: float = 500.0
    leverage: float = 1.0
    max_positions: int = 2
    stop_loss_pct: float = 15.0
    signal_min_gain_pct: float = 10.0
    signal_min_vol_usdt: float = 500_000.0
    entry_consecutive_bars: int = 2
    entry_min_gain_pct: float = 2.0
    entry_search_window_min: int = 60
    entry_stale_window_min: int = 10
    fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 5.0

    @classmethod
    def from_dict(cls, data: dict) -> "PumpFadeConfig":
        signal = data.get("signal", {})
        entry = data.get("entry", {})
        return cls(
            capital_per_trade_usd=float(data.get("capital_per_trade_usd", 500.0)),
            leverage=float(data.get("leverage", 1.0)),
            max_positions=int(data.get("max_positions", 2)),
            stop_loss_pct=float(data.get("stop_loss_pct", 15.0)),
            signal_min_gain_pct=float(signal.get("min_gain_pct", 10.0)),
            signal_min_vol_usdt=float(signal.get("min_vol_usdt", 500_000.0)),
            entry_consecutive_bars=int(entry.get("consecutive_bars", 2)),
            entry_min_gain_pct=float(entry.get("min_gain_pct", 2.0)),
            entry_search_window_min=int(entry.get("search_window_minutes", 60)),
            entry_stale_window_min=int(entry.get("stale_window_minutes", 10)),
            fee_bps_per_side=float(data.get("fee_bps_per_side", 5.0)),
            slippage_bps_per_side=float(data.get("slippage_bps_per_side", 5.0)),
        )
