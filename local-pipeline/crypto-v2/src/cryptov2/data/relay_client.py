from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_RELAY_BASE_URL = "https://www.okx.com"


class RelayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RelayClientConfig:
    base_url: str = DEFAULT_RELAY_BASE_URL
    api_key: str = ""
    secret_key: str = ""
    passphrase: str = ""
    timeout_seconds: int = 15

    @classmethod
    def from_env(cls, base_url: str | None = None, timeout_seconds: int = 15) -> "RelayClientConfig":
        resolved_base_url = (
            base_url
            or os.getenv("OKX_RELAY_BASE_URL", "")
            or os.getenv("OKX_BASE_URL", "")
            or DEFAULT_RELAY_BASE_URL
        )
        return cls(
            base_url=resolved_base_url,
            api_key=os.getenv("OKX_API_KEY", ""),
            secret_key=os.getenv("OKX_SECRET_KEY", ""),
            passphrase=os.getenv("OKX_PASSPHRASE", ""),
            timeout_seconds=timeout_seconds,
        )


class RelayClient:
    """Standalone copy of the old project's relay access semantics.

    Public endpoints do not require credentials. Private endpoints can be signed if
    credentials are present, but crypto-v2 currently uses this client for market data only.
    """

    def __init__(self, config: RelayClientConfig | None = None):
        self.config = config or RelayClientConfig.from_env()

    def _sign(self, method: str, path: str, body_str: str = "") -> dict[str, str]:
        if not all([self.config.api_key, self.config.secret_key, self.config.passphrase]):
            raise RelayError("private relay request requires OKX credentials")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        pre_hash = ts + method + path + body_str
        sign = base64.b64encode(
            hmac.new(self.config.secret_key.encode(), pre_hash.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "OK-ACCESS-KEY": self.config.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.config.passphrase,
            "Content-Type": "application/json",
        }

    def public_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {key: value for key, value in (params or {}).items() if value is not None}
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.config.base_url}{path}{query}"
        return self._request("GET", url)

    def private_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if params:
            path = f"{path}?{urlencode(params)}"
        headers = self._sign("GET", path)
        return self._request("GET", f"{self.config.base_url}{path}", headers=headers)

    def private_post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body_str = json.dumps(body) if body else ""
        headers = self._sign("POST", path, body_str)
        return self._request("POST", f"{self.config.base_url}{path}", headers=headers, body=body_str.encode())

    def _request(self, method: str, url: str, headers: dict[str, str] | None = None, body: bytes | None = None) -> dict[str, Any]:
        try:
            req = Request(url, method=method, headers=headers or {"User-Agent": "crypto-v2/0.1"}, data=body)
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {"code": "-1", "msg": str(exc)}

    def check_response(self, payload: dict[str, Any], label: str = "") -> bool:
        if payload.get("code") == "0":
            return True
        prefix = f"{label}: " if label else ""
        raise RelayError(f"{prefix}code={payload.get('code')} msg={payload.get('msg')}")

    def get_instruments(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        payload = self.public_get("/api/v5/public/instruments", {"instType": inst_type})
        self.check_response(payload, "get_instruments")
        return payload.get("data", [])

    def get_tickers(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        payload = self.public_get("/api/v5/market/tickers", {"instType": inst_type})
        self.check_response(payload, "get_tickers")
        return payload.get("data", [])

    def get_candles(self, inst_id: str, bar: str = "1m", limit: int = 300) -> list[list[str]]:
        payload = self.public_get("/api/v5/market/candles", {"instId": inst_id, "bar": bar, "limit": str(limit)})
        self.check_response(payload, f"get_candles({inst_id})")
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
            {"instId": inst_id, "bar": bar, "limit": str(limit), "after": after, "before": before},
        )
        self.check_response(payload, f"get_history_candles({inst_id})")
        return payload.get("data", [])
