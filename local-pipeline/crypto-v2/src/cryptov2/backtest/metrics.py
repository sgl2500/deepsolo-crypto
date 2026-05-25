from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Any

from cryptov2.data.schemas import Position, fmt_ts


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    mdd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return mdd


def summarize_positions(positions: list[Position], field: str = "net_pnl_pct") -> dict[str, Any]:
    pnls = [getattr(pos, field) for pos in positions if getattr(pos, field) is not None]
    if not pnls:
        return {"trades": 0}
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    by_month: dict[str, list[float]] = defaultdict(list)
    for pos, pnl in zip(positions, pnls):
        by_month[fmt_ts(pos.entry_ts)[:7]].append(pnl)
    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 2),
        "total_pnl_pct_sum": round(sum(pnls), 4),
        "avg_pnl_pct": round(statistics.mean(pnls), 4),
        "median_pnl_pct": round(statistics.median(pnls), 4),
        "avg_win_pct": round(statistics.mean(wins), 4) if wins else 0,
        "avg_loss_pct": round(statistics.mean(losses), 4) if losses else 0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses and sum(losses) else math.inf,
        "max_trade_pct": round(max(pnls), 4),
        "min_trade_pct": round(min(pnls), 4),
        "max_drawdown_pct_sum": round(max_drawdown(pnls), 4),
        "reasons": dict(Counter(pos.reason for pos in positions)),
        "entry_range": [fmt_ts(positions[0].entry_ts), fmt_ts(positions[-1].entry_ts)],
        "by_month": {key: round(sum(vals), 4) for key, vals in sorted(by_month.items())},
    }


def positions_to_dicts(positions: list[Position]) -> list[dict[str, Any]]:
    rows = []
    for pos in positions:
        row = asdict(pos)
        row["entry_time"] = fmt_ts(pos.entry_ts)
        if pos.exit_ts is not None:
            row["exit_time"] = fmt_ts(pos.exit_ts)
        rows.append(row)
    return rows
