from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cryptov2.data.okx_candles import Candle
from cryptov2.data.schemas import Bar, BarSize
from cryptov2.data.storage.candle_store import CandleStore
from cryptov2.data.storage.gzip_partition_store import GzipPartitionedCandleStore


class CandleStoreProtocol(Protocol):
    def symbols(self, bar: BarSize = "5m") -> list[str]: ...
    def read_candles(self, bar: BarSize, inst_id: str, confirmed_only: bool = True) -> list[Candle]: ...
    def read_bars(self, bar: BarSize, inst_id: str) -> list[Bar]: ...
    def upsert_candles(self, bar: BarSize, inst_id: str, candles: list[Candle]) -> int: ...


def create_candle_store(backend: str, root: Path | str) -> CandleStoreProtocol:
    if backend == "csv":
        return CandleStore(root)
    if backend == "gzip_partition":
        return GzipPartitionedCandleStore(root)
    raise ValueError(f"unknown candle store backend: {backend}")
