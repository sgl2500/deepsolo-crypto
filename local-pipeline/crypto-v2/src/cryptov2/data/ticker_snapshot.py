from __future__ import annotations

import bisect
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from cryptov2.data.schemas import fmt_ts


@dataclass(frozen=True, slots=True)
class TickerSnapshotRow:
    inst_id: str
    last: float
    bid_px: float
    ask_px: float
    open24h: float
    high24h: float
    low24h: float
    vol_ccy_24h: float
    vol_usdt_24h: float


def _float_attr(item: Any, name: str, default: float = 0.0) -> float:
    try:
        return float(getattr(item, name, default) or default)
    except (TypeError, ValueError):
        return default


def ticker_to_snapshot_row(inst_id: str, ticker: Any) -> TickerSnapshotRow:
    last = _float_attr(ticker, "last")
    vol_ccy_24h = _float_attr(ticker, "vol_ccy_24h")
    vol_usdt_24h = _float_attr(ticker, "vol_usdt_24h", vol_ccy_24h * last)
    return TickerSnapshotRow(
        inst_id=inst_id,
        last=last,
        bid_px=_float_attr(ticker, "bid_px"),
        ask_px=_float_attr(ticker, "ask_px"),
        open24h=_float_attr(ticker, "open24h"),
        high24h=_float_attr(ticker, "high24h"),
        low24h=_float_attr(ticker, "low24h"),
        vol_ccy_24h=vol_ccy_24h,
        vol_usdt_24h=vol_usdt_24h,
    )


class TickerSnapshotStore:
    """Store point-in-time ticker snapshots for replayable volume gates."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def partition_date(self, ts_ms: int) -> str:
        return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")

    def path(self, ts_ms: int) -> Path:
        date = self.partition_date(ts_ms)
        return self.root / f"date={date}" / f"{ts_ms}.json"

    def write_snapshot(
        self,
        ts_ms: int,
        tickers: Mapping[str, Any],
        source: str = "live",
    ) -> Path:
        rows = [
            asdict(ticker_to_snapshot_row(inst_id, ticker))
            for inst_id, ticker in sorted(tickers.items())
        ]
        payload = {
            "meta": {
                "ts": ts_ms,
                "time": fmt_ts(ts_ms),
                "source": source,
                "count": len(rows),
            },
            "tickers": rows,
        }
        path = self.path(ts_ms)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        tmp.replace(path)
        return path

    def read_snapshot(self, path: Path | str) -> dict[str, Any]:
        return json.loads(Path(path).read_text())

    def list_snapshots(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.glob("date=*/*.json"))

    def latest_before(self, ts_ms: int) -> Path | None:
        candidates = []
        for path in self.list_snapshots():
            try:
                snap_ts = int(path.stem)
            except ValueError:
                continue
            if snap_ts <= ts_ms:
                candidates.append((snap_ts, path))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def read_latest_before(self, ts_ms: int) -> dict[str, Any] | None:
        path = self.latest_before(ts_ms)
        return self.read_snapshot(path) if path else None


class TickerSnapshotVolumeGate:
    """Replay live ticker snapshots as the strategy volume gate."""

    def __init__(self, store: TickerSnapshotStore):
        self.store = store
        self._index: list[tuple[int, Path]] | None = None
        self._cache: dict[Path, dict[str, float]] = {}

    def _load_index(self) -> list[tuple[int, Path]]:
        if self._index is None:
            rows: list[tuple[int, Path]] = []
            for path in self.store.list_snapshots():
                try:
                    rows.append((int(path.stem), path))
                except ValueError:
                    continue
            self._index = sorted(rows, key=lambda item: item[0])
        return self._index

    def latest_path_before(self, ts_ms: int) -> Path | None:
        index = self._load_index()
        if not index:
            return None
        pos = bisect.bisect_right([item[0] for item in index], ts_ms) - 1
        return index[pos][1] if pos >= 0 else None

    def _snapshot_volumes(self, path: Path) -> dict[str, float]:
        if path not in self._cache:
            payload = self.store.read_snapshot(path)
            volumes = {}
            for row in payload.get("tickers", []):
                inst_id = row.get("inst_id")
                if not inst_id:
                    continue
                try:
                    volumes[inst_id] = float(row.get("vol_usdt_24h") or 0)
                except (TypeError, ValueError):
                    volumes[inst_id] = 0.0
            self._cache[path] = volumes
        return self._cache[path]

    def volume_usdt(self, inst_id: str, ts_ms: int) -> float | None:
        path = self.latest_path_before(ts_ms)
        if path is None:
            return None
        return self._snapshot_volumes(path).get(inst_id)
