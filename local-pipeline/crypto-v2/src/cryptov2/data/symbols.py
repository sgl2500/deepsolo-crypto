from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from cryptov2.data.market import Instrument, MarketDataService


def load_usdt_swap_symbols(service: MarketDataService, live_only: bool = True) -> list[Instrument]:
    """Return only OKX USDT-settled SWAP instruments."""
    return service.usdt_swap_instruments(live_only=live_only)


def write_symbol_catalog(path: Path | str, instruments: list[Instrument], meta: dict | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta or {},
        "summary": {"symbols": len(instruments), "inst_type": "SWAP", "settle_ccy": "USDT"},
        "symbols": [asdict(item) for item in instruments],
    }
    with path.open("w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def read_symbol_catalog(path: Path | str) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    payload = json.load(path.open())
    return [item["inst_id"] for item in payload.get("symbols", [])]
