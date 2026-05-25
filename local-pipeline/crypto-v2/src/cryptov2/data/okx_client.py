from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OkxRestError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OkxRestClientConfig:
    base_url: str = "https://www.okx.com"
    timeout_seconds: int = 15
    max_retries: int = 3
    retry_sleep_seconds: float = 0.5


class OkxRestClient:
    """Small public OKX REST client using stdlib only."""

    def __init__(self, config: OkxRestClientConfig | None = None):
        self.config = config or OkxRestClientConfig()

    def public_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {key: value for key, value in (params or {}).items() if value is not None}
        url = f"{self.config.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                req = Request(url, headers={"User-Agent": "crypto-v2/0.1"})
                with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                if payload.get("code") not in (None, "0"):
                    raise OkxRestError(f"OKX error {payload.get('code')}: {payload.get('msg')}")
                return payload
            except (HTTPError, URLError, TimeoutError, OkxRestError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_sleep_seconds * attempt)
        raise OkxRestError(f"GET {url} failed: {last_error}")

    def get_instruments(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        return self.public_get("/api/v5/public/instruments", {"instType": inst_type}).get("data", [])

    def get_tickers(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        return self.public_get("/api/v5/market/tickers", {"instType": inst_type}).get("data", [])

    def get_candles(self, inst_id: str, bar: str = "1m", limit: int = 300) -> list[list[str]]:
        payload = self.public_get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": str(limit)},
        )
        return payload.get("data", [])

    def get_history_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        limit: int = 300,
        after: str | None = None,
        before: str | None = None,
    ) -> list[list[str]]:
        payload = self.public_get(
            "/api/v5/market/history-candles",
            {
                "instId": inst_id,
                "bar": bar,
                "limit": str(limit),
                "after": after,
                "before": before,
            },
        )
        return payload.get("data", [])
