from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from cryptov2.data.market import MarketDataClient, MarketDataService, Ticker
from cryptov2.data.okx_candles import parse_okx_candles
from cryptov2.data.schemas import Bar


class PumpFadeMarketData(Protocol):
    def get_tickers(self) -> dict[str, Ticker]: ...
    def get_ticker(self, inst_id: str) -> Ticker | None: ...
    def get_bars(self, inst_id: str, bar: str, limit: int) -> list[Bar]: ...
    def get_bars_batch(
        self,
        inst_ids: list[str],
        bar: str,
        limit: int,
        max_workers: int,
    ) -> dict[str, list[Bar]]: ...


class RestPumpFadeMarketData:
    """Bot-compatible recent market data adapter backed by OKX/relay REST."""

    def __init__(self, client: MarketDataClient):
        self.client = client
        self.service = MarketDataService(client)

    def get_tickers(self) -> dict[str, Ticker]:
        return self.service.tickers()

    def get_ticker(self, inst_id: str) -> Ticker | None:
        public_get = getattr(self.client, "public_get", None)
        if public_get is None:
            tickers = self.get_tickers()
            return tickers.get(inst_id)
        payload = public_get("/api/v5/market/ticker", {"instId": inst_id})
        if payload.get("code") not in (None, "0") or not payload.get("data"):
            return None
        return Ticker.from_okx(payload["data"][0])

    def get_bars(self, inst_id: str, bar: str, limit: int) -> list[Bar]:
        rows = self.client.get_candles(inst_id, bar=bar, limit=limit)
        candles = parse_okx_candles(inst_id, rows, source="live_recent")
        return [candle.to_bar() for candle in candles]

    def get_bars_batch(
        self,
        inst_ids: list[str],
        bar: str,
        limit: int,
        max_workers: int,
    ) -> dict[str, list[Bar]]:
        if not inst_ids:
            return {}
        output: dict[str, list[Bar]] = {}
        batch_size = max(1, max_workers)
        for start in range(0, len(inst_ids), batch_size):
            batch = inst_ids[start : start + batch_size]
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = {
                    pool.submit(self.get_bars, inst_id, bar, limit): inst_id for inst_id in batch
                }
                for future in as_completed(futures):
                    inst_id = futures[future]
                    try:
                        bars = future.result()
                    except Exception:
                        bars = []
                    if bars:
                        output[inst_id] = bars
        return output
