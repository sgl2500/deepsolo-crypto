#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cryptov2.data.instruments_dim import sync_instrument_dim
from cryptov2.data.okx_client import OkxRestClient, OkxRestClientConfig
from cryptov2.data.relay_client import RelayClient, RelayClientConfig


def build_client(args):
    if args.source == "relay":
        return RelayClient(
            RelayClientConfig.from_env(
                args.base_url,
                timeout_seconds=args.timeout,
            )
        )
    return OkxRestClient(
        OkxRestClientConfig(
            base_url=args.base_url or "https://www.okx.com",
            timeout_seconds=args.timeout,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync OKX USDT SWAP instrument dimension.")
    parser.add_argument("--source", choices=["relay", "okx"], default="relay")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--dim-catalog",
        type=Path,
        default=ROOT / "data" / "catalog" / "instruments_okx_usdt_swap_dim.json",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=ROOT / "data" / "catalog" / "instrument_snapshots" / "okx_swap",
    )
    parser.add_argument(
        "--legacy-symbol-catalog",
        type=Path,
        default=ROOT / "data" / "catalog" / "symbols_usdt_swap.json",
    )
    parser.add_argument("--no-snapshot", action="store_true")
    parser.add_argument("--no-legacy-symbol-catalog", action="store_true")
    args = parser.parse_args()

    client = build_client(args)
    raw_rows = client.get_instruments("SWAP")
    _payload, stats = sync_instrument_dim(
        raw_rows=raw_rows,
        dim_path=args.dim_catalog,
        snapshot_dir=None if args.no_snapshot else args.snapshot_dir,
        legacy_symbol_catalog=None
        if args.no_legacy_symbol_catalog
        else args.legacy_symbol_catalog,
        source=args.source,
    )
    print(
        "instrument dim synced: "
        f"new={stats['new']} online={stats['online']} offline={stats['offline']} "
        f"changed_state={stats['changed_state']} missing={stats['missing']}"
    )
    print(f"dim catalog: {args.dim_catalog}")


if __name__ == "__main__":
    main()
