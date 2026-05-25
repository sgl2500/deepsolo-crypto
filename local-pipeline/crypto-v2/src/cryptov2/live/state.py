from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any


class JsonStateStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"positions": [], "orders": [], "events": []}
        with self.path.open() as f:
            return json.load(f)

    def save(self, state: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(self.path)

    def append_event(self, event: Any) -> None:
        state = self.load()
        payload = asdict(event) if hasattr(event, "__dataclass_fields__") else event
        state.setdefault("events", []).append(payload)
        self.save(state)
