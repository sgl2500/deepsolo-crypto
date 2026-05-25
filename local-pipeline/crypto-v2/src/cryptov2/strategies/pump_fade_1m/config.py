from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PumpFade1mConfig:
    capital_per_trade_usd: float = 100.0
    leverage: float = 1.0
    max_positions: int = 2
    stop_loss_pct: float = 20.0
    signal_min_gain_pct: float = 13.0
    signal_min_vol_usdt: float = 1_000_000.0
    entry_consecutive_bars: int = 2
    entry_min_gain_pct: float = 0.8
    entry_search_window_min: int = 60
    entry_stale_window_min: int = 2
    entry_max_delay_min: int | None = None
    entry_max_trigger_pct: float | None = None
    entry_allowed_hours_cst: tuple[int, ...] | None = None
    exit_hold_minutes: int = 120
    fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 5.0

    @classmethod
    def from_dict(cls, data: dict) -> "PumpFade1mConfig":
        signal = data.get("signal", {})
        entry = data.get("entry", {})
        exit_cfg = data.get("exit", {})
        return cls(
            capital_per_trade_usd=float(data.get("capital_per_trade_usd", 100.0)),
            leverage=float(data.get("leverage", 1.0)),
            max_positions=int(data.get("max_positions", 2)),
            stop_loss_pct=float(data.get("stop_loss_pct", 20.0)),
            signal_min_gain_pct=float(signal.get("min_gain_pct", 13.0)),
            signal_min_vol_usdt=float(signal.get("min_vol_usdt", 1_000_000.0)),
            entry_consecutive_bars=int(entry.get("consecutive_bars", 2)),
            entry_min_gain_pct=float(entry.get("min_gain_pct", 0.8)),
            entry_search_window_min=int(entry.get("search_window_minutes", 60)),
            entry_stale_window_min=int(entry.get("stale_window_minutes", 2)),
            entry_max_delay_min=(
                int(entry["max_delay_minutes"]) if entry.get("max_delay_minutes") is not None else None
            ),
            entry_max_trigger_pct=(
                float(entry["max_trigger_pct"]) if entry.get("max_trigger_pct") is not None else None
            ),
            entry_allowed_hours_cst=(
                tuple(int(hour) for hour in entry["allowed_hours_cst"])
                if entry.get("allowed_hours_cst") is not None
                else None
            ),
            exit_hold_minutes=int(exit_cfg.get("hold_minutes", 120)),
            fee_bps_per_side=float(data.get("fee_bps_per_side", 5.0)),
            slippage_bps_per_side=float(data.get("slippage_bps_per_side", 5.0)),
        )
