from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol, Sequence

from cryptov2.data.schemas import CST
from cryptov2.strategies.pump_fade.config import PumpFadeConfig

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
BOT_ENTRY_MAX_5M_BARS = 12


class BarLike(Protocol):
    ts: int
    open: float
    close: float

    @property
    def change_pct(self) -> float: ...


class TickerLike(Protocol):
    vol_usdt_24h: float


@dataclass(frozen=True, slots=True)
class BotSignal:
    """Signal payload kept compatible with the original live bot watchlist."""

    inst_id: str
    confirm_ts: int
    confirm_time: str
    cum_gain: float

    def to_state_dict(self) -> dict:
        return {
            "inst_id": self.inst_id,
            "confirm_ts": self.confirm_ts,
            "confirm_time": self.confirm_time,
            "cum_gain": self.cum_gain,
        }


@dataclass(frozen=True, slots=True)
class BotEntry:
    """Entry payload kept compatible with the original live bot state."""

    entry_price: float
    entry_ts: int
    trigger: list[float]
    delay_min: float

    def to_state_dict(self) -> dict:
        return {
            "entry_price": self.entry_price,
            "entry_ts": self.entry_ts,
            "trigger": self.trigger,
            "delay_min": self.delay_min,
        }


def format_confirm_time(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=CST).strftime("%Y-%m-%d %H:%M")


def filter_bot_signal_candidates(
    tickers: Mapping[str, TickerLike],
    config: PumpFadeConfig,
) -> list[str]:
    """Match the original bot's USDT swap + ticker volume pre-filter."""

    return [
        inst_id
        for inst_id, ticker in tickers.items()
        if inst_id.endswith("-USDT-SWAP") and ticker.vol_usdt_24h >= config.signal_min_vol_usdt
    ]


def scan_bot_signals(
    tickers: Mapping[str, TickerLike],
    bars_1h_by_symbol: Mapping[str, Sequence[BarLike]],
    config: PumpFadeConfig,
    now_ts: int,
) -> list[BotSignal]:
    """Reproduce the original bot.py scan_signals() decision rules.

    The original live bot receives recent OKX candles where the last 1H row is
    the in-progress candle, so it scans only bars[:-1]. Keep that convention
    here to avoid silent signal drift during migration.
    """

    candidates = filter_bot_signal_candidates(tickers, config)
    signals: list[BotSignal] = []
    seen: set[tuple[str, int]] = set()
    expire_ms = config.entry_search_window_min * MINUTE_MS

    for inst_id in candidates:
        bars = list(bars_1h_by_symbol.get(inst_id, []))
        if len(bars) < 3:
            continue
        completed = bars[:-1]
        for idx in range(len(completed) - 1):
            k1 = completed[idx]
            k2 = completed[idx + 1]
            if not (k1.close > k1.open and k2.close > k2.open and k1.open > 0):
                continue
            gain = (k2.close - k1.open) / k1.open * 100.0
            if gain < config.signal_min_gain_pct:
                continue
            key = (inst_id, k2.ts)
            if key in seen:
                continue
            seen.add(key)

            confirm_ts = k2.ts + HOUR_MS
            if now_ts > confirm_ts + expire_ms:
                continue
            signals.append(
                BotSignal(
                    inst_id=inst_id,
                    confirm_ts=confirm_ts,
                    confirm_time=format_confirm_time(confirm_ts),
                    cum_gain=round(gain, 1),
                )
            )

    signals.sort(key=lambda item: item.cum_gain, reverse=True)
    return signals


def find_bot_entry(
    bars_5m: Sequence[BarLike],
    confirm_ts: int,
    config: PumpFadeConfig,
    now_ts: int | None = None,
    enforce_stale_guard: bool = False,
) -> BotEntry | None:
    """Reproduce the original bot.py check_entry() rules.

    Backtests call this without now_ts/stale enforcement. Live migration should
    pass now_ts and enforce_stale_guard=True to preserve the original "only
    enter on triggers from the last 10 minutes" protection.
    """

    if now_ts is not None and now_ts > confirm_ts + config.entry_search_window_min * MINUTE_MS:
        return None

    after = [bar for bar in bars_5m if bar.ts >= confirm_ts]
    entry_n = config.entry_consecutive_bars
    if len(after) < entry_n + 1:
        return None

    max_scan = min(len(after) - entry_n, BOT_ENTRY_MAX_5M_BARS)
    for offset in range(max_scan):
        trigger: list[float] = []
        matched = True
        for step in range(entry_n):
            bar = after[offset + step]
            if bar.close <= bar.open:
                matched = False
                break
            change_pct = bar.change_pct
            if change_pct < config.entry_min_gain_pct:
                matched = False
                break
            trigger.append(round(change_pct, 1))
        if not matched:
            continue

        entry_bar = after[offset + entry_n]
        if enforce_stale_guard and now_ts is not None:
            if entry_bar.ts < now_ts - config.entry_stale_window_min * MINUTE_MS:
                continue

        delay_min = (entry_bar.ts - confirm_ts) / MINUTE_MS
        return BotEntry(
            entry_price=entry_bar.open,
            entry_ts=entry_bar.ts,
            trigger=trigger,
            delay_min=delay_min,
        )
    return None
