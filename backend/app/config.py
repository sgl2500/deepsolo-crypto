from __future__ import annotations

import os
from pathlib import Path


DATA_ROOT = Path(
    os.getenv(
        "CRYPTO_DATA_ROOT",
        "/Users/sunguanlong/Desktop/crypto/crypto-v2/data/normalized_gzip",
    )
)

APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Shanghai")

TIMEFRAMES = {
    "1m": "candles_1m",
    "5m": "candles_5m",
    "15m": "candles_15m",
    "1H": "candles_1H",
    "1D": "candles_1D",
}
