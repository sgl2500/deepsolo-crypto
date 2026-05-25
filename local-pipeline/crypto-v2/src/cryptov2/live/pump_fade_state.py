from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PumpFadeStateStore:
    """Old-bot-compatible JSON state split into positions/trades/watchlist."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def _read(self, name: str, default: Any) -> Any:
        path = self.path(name)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return default

    def _write(self, name: str, payload: Any) -> None:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        tmp.replace(path)

    def load_positions(self) -> dict[str, dict[str, Any]]:
        payload = self._read("positions", {})
        return payload if isinstance(payload, dict) else {}

    def save_positions(self, positions: dict[str, dict[str, Any]]) -> None:
        self._write("positions", positions)

    def load_trades(self) -> list[dict[str, Any]]:
        payload = self._read("trades", [])
        return payload if isinstance(payload, list) else []

    def append_trade(self, trade: dict[str, Any]) -> None:
        trades = self.load_trades()
        trades.append(trade)
        self._write("trades", trades)

    def load_watchlist(self) -> list[dict[str, Any]]:
        payload = self._read("watchlist", [])
        return payload if isinstance(payload, list) else []

    def save_watchlist(self, watchlist: list[dict[str, Any]]) -> None:
        self._write("watchlist", watchlist)
