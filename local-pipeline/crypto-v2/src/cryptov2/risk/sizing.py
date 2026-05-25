from __future__ import annotations


def fixed_notional(capital_per_trade_usd: float, leverage: float = 1.0) -> float:
    return capital_per_trade_usd * leverage


def risk_based_notional(max_loss_usd: float, stop_distance_pct: float) -> float:
    if stop_distance_pct <= 0:
        raise ValueError("stop_distance_pct must be positive")
    return max_loss_usd / (stop_distance_pct / 100.0)
