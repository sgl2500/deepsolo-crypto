from __future__ import annotations

from pathlib import Path

from cryptov2.data.providers.csv_provider import aggregate_1h_from_5m
from cryptov2.data.schemas import Bar, BarSize
from cryptov2.data.storage.factory import CandleStoreProtocol, create_candle_store


class StoreKlineProvider:
    """Read strategy bars from the normalized candle store layout."""

    def __init__(self, root: Path | str, backend: str = "gzip_partition"):
        self.root = Path(root)
        self.backend = backend
        self.store: CandleStoreProtocol = create_candle_store(backend, self.root)

    def symbols(self, bar: BarSize = "5m") -> list[str]:
        return self.store.symbols(bar)

    def load_bars(self, inst_id: str, bar: BarSize) -> list[Bar]:
        return self.store.read_bars(bar, inst_id)

    def load_1h_from_5m(self, inst_id: str) -> list[Bar]:
        return aggregate_1h_from_5m(self.load_bars(inst_id, "5m"))
