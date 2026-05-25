from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DownloadState:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"symbols": {}}
        with self.path.open() as f:
            return json.load(f)

    def save(self, state: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(self.path)

    def get_symbol(self, inst_id: str) -> dict[str, Any]:
        return self.load().setdefault("symbols", {}).get(inst_id, {})

    def update_symbol(self, inst_id: str, patch: dict[str, Any]) -> None:
        state = self.load()
        symbols = state.setdefault("symbols", {})
        current = symbols.setdefault(inst_id, {})
        current.update(patch)
        self.save(state)
