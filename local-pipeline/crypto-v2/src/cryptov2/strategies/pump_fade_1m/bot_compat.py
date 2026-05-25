from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from cryptov2.data.schemas import CST
from cryptov2.strategies.pump_fade_1m.config import PumpFade1mConfig

MINUTE_MS = 60_000


class BarLike(Protocol):
    ts: int
    open: float
    close: float

    @property
    def change_pct(self) -> float: ...


@dataclass(frozen=True, slots=True)
class PumpFade1mEntry:
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


def find_1m_entry(
    bars_1m: Sequence[BarLike],
    confirm_ts: int,
    config: PumpFade1mConfig,
    now_ts: int | None = None,
    enforce_stale_guard: bool = False,
) -> PumpFade1mEntry | None:
    """Find the old 1m bot style entry after a 1H pump signal.

    The strategy sells short on the open of the bar after N consecutive green
    1m trigger bars. Live mode can enforce the original 2-minute stale guard so
    restarted bots do not chase old triggers.
    """

    search_ms = config.entry_search_window_min * MINUTE_MS
    if now_ts is not None and now_ts > confirm_ts + search_ms:
        return None

    after = [bar for bar in bars_1m if bar.ts >= confirm_ts]
    entry_n = config.entry_consecutive_bars
    if len(after) < entry_n + 1:
        return None

    max_scan = min(len(after) - entry_n, config.entry_search_window_min)
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
        if config.entry_max_trigger_pct is not None and max(trigger) > config.entry_max_trigger_pct:
            return None
        if entry_bar.ts > confirm_ts + search_ms:
            continue
        if enforce_stale_guard and now_ts is not None:
            if entry_bar.ts < now_ts - config.entry_stale_window_min * MINUTE_MS:
                continue

        delay_min = (entry_bar.ts - confirm_ts) / MINUTE_MS
        if config.entry_max_delay_min is not None and delay_min > config.entry_max_delay_min:
            return None
        if config.entry_allowed_hours_cst is not None:
            entry_hour = datetime.fromtimestamp(entry_bar.ts / 1000, tz=CST).hour
            if entry_hour not in config.entry_allowed_hours_cst:
                return None

        return PumpFade1mEntry(
            entry_price=entry_bar.open,
            entry_ts=entry_bar.ts,
            trigger=trigger,
            delay_min=delay_min,
        )
    return None
