from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchdogStatus:
    ok: bool
    messages: list[str]


class Watchdog:
    def check(self) -> WatchdogStatus:
        return WatchdogStatus(True, [])
