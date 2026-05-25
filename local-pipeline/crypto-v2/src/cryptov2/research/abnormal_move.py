from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from cryptov2.data.schemas import HOUR_MS

MINUTE_MS = 60_000


@dataclass(frozen=True, slots=True)
class BarLike:
    ts: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class AbnormalEvent:
    inst_id: str
    bar_ts: int
    event_close_ts: int
    open: float
    high: float
    low: float
    close: float
    gain_pct: float
    prev_high_close: float


@dataclass(frozen=True, slots=True)
class TimeRange:
    start_ts: int
    end_ts: int


@dataclass(frozen=True, slots=True)
class TradeResult:
    inst_id: str
    event_close_ts: int
    side: str
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    gross_pct: float
    net_pct: float
    event_gain_pct: float


@dataclass(frozen=True, slots=True)
class ShortEntry:
    inst_id: str
    event_close_ts: int
    entry_ts: int
    entry_price: float
    trigger_price: float
    delay_min: float
    event_gain_pct: float


@dataclass(frozen=True, slots=True)
class ShortTrade:
    inst_id: str
    event_close_ts: int
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    gross_pct: float
    net_pct: float
    event_gain_pct: float
    exit_reason: str


def scan_abnormal_events(
    inst_id: str,
    bars_1h: list[BarLike],
    *,
    lookback_hours: int = 72,
    min_gain_pct: float = 15.0,
) -> list[AbnormalEvent]:
    events: list[AbnormalEvent] = []
    if len(bars_1h) <= lookback_hours:
        return events
    for idx in range(lookback_hours, len(bars_1h)):
        bar = bars_1h[idx]
        if bar.open <= 0:
            continue
        gain_pct = (bar.close - bar.open) / bar.open * 100.0
        if gain_pct <= min_gain_pct:
            continue
        prev_high_close = max(prev.close for prev in bars_1h[idx - lookback_hours:idx])
        if bar.close <= prev_high_close:
            continue
        events.append(
            AbnormalEvent(
                inst_id=inst_id,
                bar_ts=bar.ts,
                event_close_ts=bar.ts + HOUR_MS,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                gain_pct=gain_pct,
                prev_high_close=prev_high_close,
            )
        )
    return events


def merge_time_ranges(ranges: list[TimeRange], *, gap_ms: int = 0) -> list[TimeRange]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda item: (item.start_ts, item.end_ts))
    merged = [ordered[0]]
    for current in ordered[1:]:
        last = merged[-1]
        if current.start_ts <= last.end_ts + gap_ms:
            merged[-1] = TimeRange(last.start_ts, max(last.end_ts, current.end_ts))
            continue
        merged.append(current)
    return merged


def select_bars_in_ranges(bars: list[BarLike], ranges: list[TimeRange]) -> list[BarLike]:
    if not bars or not ranges:
        return []
    ts_list = [bar.ts for bar in bars]
    selected: list[BarLike] = []
    for window in ranges:
        start_idx = bisect_left(ts_list, window.start_ts)
        end_idx = bisect_left(ts_list, window.end_ts)
        selected.extend(bars[start_idx:end_idx])
    return selected


def hour_close_after(ts_ms: int) -> int:
    return ((ts_ms + HOUR_MS - 1) // HOUR_MS) * HOUR_MS


def _entry_move(event: AbnormalEvent, entry_mode: str) -> float:
    if entry_mode == "body":
        return event.close - event.open
    if entry_mode == "range":
        return event.high - event.low
    raise ValueError(f"unknown entry mode: {entry_mode}")


def find_short_continuation_entry(
    event: AbnormalEvent,
    minute_bars: list[BarLike],
    *,
    entry_mode: str = "body",
    trigger_pct: float = 20.0,
    search_hours: int = 2,
) -> ShortEntry | None:
    move = _entry_move(event, entry_mode)
    if move <= 0 or not minute_bars:
        return None

    trigger_price = event.close + trigger_pct / 100.0 * move
    search_end_ts = event.event_close_ts + search_hours * HOUR_MS
    ts_list = [bar.ts for bar in minute_bars]
    start_idx = bisect_left(ts_list, event.event_close_ts)
    end_idx = bisect_left(ts_list, search_end_ts)
    for idx in range(start_idx, end_idx):
        bar = minute_bars[idx]
        if bar.low <= trigger_price <= bar.high:
            return ShortEntry(
                inst_id=event.inst_id,
                event_close_ts=event.event_close_ts,
                entry_ts=bar.ts,
                entry_price=trigger_price,
                trigger_price=trigger_price,
                delay_min=(bar.ts - event.event_close_ts) / MINUTE_MS,
                event_gain_pct=event.gain_pct,
            )
    return None


def simulate_short_continuation_trade(
    event: AbnormalEvent,
    minute_bars: list[BarLike],
    *,
    entry_mode: str = "body",
    trigger_pct: float = 20.0,
    search_hours: int = 2,
    hold_hours: int = 48,
    roundtrip_cost_pct: float = 0.2,
    stop_loss_pct: float | None = None,
) -> ShortTrade | None:
    entry = find_short_continuation_entry(
        event,
        minute_bars,
        entry_mode=entry_mode,
        trigger_pct=trigger_pct,
        search_hours=search_hours,
    )
    if entry is None:
        return None

    ts_list = [bar.ts for bar in minute_bars]
    entry_idx = bisect_left(ts_list, entry.entry_ts)
    exit_target_ts = hour_close_after(entry.entry_ts + hold_hours * HOUR_MS)
    exit_bar_ts = exit_target_ts - MINUTE_MS
    stop_price = entry.entry_price * (1.0 + stop_loss_pct / 100.0) if stop_loss_pct is not None else None
    exit_price = None
    exit_ts = None
    exit_reason = "time_exit"
    for idx in range(entry_idx, len(minute_bars)):
        bar = minute_bars[idx]
        if stop_price is not None and bar.high >= stop_price:
            exit_price = stop_price
            exit_ts = bar.ts
            exit_reason = "stop_loss"
            break
        if bar.ts == exit_bar_ts:
            exit_price = bar.close
            exit_ts = bar.ts
            break
    if exit_price is None or exit_ts is None:
        return None

    gross_pct = -(exit_price - entry.entry_price) / entry.entry_price * 100.0
    net_pct = gross_pct - roundtrip_cost_pct
    return ShortTrade(
        inst_id=event.inst_id,
        event_close_ts=event.event_close_ts,
        entry_ts=entry.entry_ts,
        exit_ts=exit_ts,
        entry_price=entry.entry_price,
        exit_price=exit_price,
        gross_pct=gross_pct,
        net_pct=net_pct,
        event_gain_pct=event.gain_pct,
        exit_reason=exit_reason,
    )


def simulate_pullback_trade(
    event: AbnormalEvent,
    minute_bars: list[BarLike],
    *,
    entry_mode: str = "body",
    trigger_pct: float = 30.0,
    search_hours: int = 1,
    hold_hours: int = 2,
    roundtrip_cost_pct: float = 0.2,
) -> TradeResult | None:
    if entry_mode == "body":
        move = event.close - event.open
    elif entry_mode == "range":
        move = event.high - event.low
    else:
        raise ValueError(f"unknown entry mode: {entry_mode}")
    if move <= 0 or not minute_bars:
        return None

    long_level = event.close - trigger_pct / 100.0 * move
    short_level = event.close + trigger_pct / 100.0 * move
    search_end_ts = event.event_close_ts + search_hours * HOUR_MS
    ts_list = [bar.ts for bar in minute_bars]
    start_idx = bisect_left(ts_list, event.event_close_ts)
    end_idx = bisect_left(ts_list, search_end_ts)

    triggered_side: str | None = None
    entry_ts = 0
    entry_price = 0.0
    for idx in range(start_idx, end_idx):
        bar = minute_bars[idx]
        hit_long = bar.low <= long_level <= bar.high
        hit_short = bar.low <= short_level <= bar.high
        if hit_long and hit_short:
            return None
        if hit_long:
            triggered_side = "long"
            entry_ts = bar.ts
            entry_price = long_level
            break
        if hit_short:
            triggered_side = "short"
            entry_ts = bar.ts
            entry_price = short_level
            break
    if triggered_side is None:
        return None

    exit_target_ts = hour_close_after(entry_ts + hold_hours * HOUR_MS)
    exit_bar_ts = exit_target_ts - MINUTE_MS
    exit_idx = bisect_left(ts_list, exit_bar_ts)
    if exit_idx >= len(minute_bars) or minute_bars[exit_idx].ts != exit_bar_ts:
        return None

    exit_bar = minute_bars[exit_idx]
    if triggered_side == "long":
        gross_pct = (exit_bar.close - entry_price) / entry_price * 100.0
    else:
        gross_pct = -(exit_bar.close - entry_price) / entry_price * 100.0
    net_pct = gross_pct - roundtrip_cost_pct
    return TradeResult(
        inst_id=event.inst_id,
        event_close_ts=event.event_close_ts,
        side=triggered_side,
        entry_ts=entry_ts,
        exit_ts=exit_bar.ts,
        entry_price=entry_price,
        exit_price=exit_bar.close,
        gross_pct=gross_pct,
        net_pct=net_pct,
        event_gain_pct=event.gain_pct,
    )
