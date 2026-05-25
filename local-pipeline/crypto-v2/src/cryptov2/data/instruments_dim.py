from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from cryptov2.data.market import Instrument
from cryptov2.data.symbols import write_symbol_catalog


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def date_key_from_iso(value: str) -> str:
    return value[:10]


def load_instrument_dim(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"meta": {}, "summary": {"symbols": 0}, "symbols": []}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    payload.setdefault("meta", {})
    payload.setdefault("summary", {})
    payload.setdefault("symbols", [])
    return payload


def save_instrument_dim(path: Path | str, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def is_online_state(state: str | None) -> bool:
    return state in ("", None, "live")


def _row_from_okx(raw: dict[str, Any], now: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = dict(existing or {})
    state = raw.get("state", "")
    was_online = bool(existing.get("is_online", False))
    online = is_online_state(state)
    row = {
        **existing,
        "inst_id": raw.get("instId", existing.get("inst_id", "")),
        "inst_type": raw.get("instType", existing.get("inst_type", "")),
        "settle_ccy": raw.get("settleCcy", existing.get("settle_ccy", "")),
        "state": state,
        "is_online": online,
        "data_enabled": existing.get("data_enabled", True),
        "backfill_enabled": existing.get("backfill_enabled", True),
        "first_seen_at": existing.get("first_seen_at") or now,
        "last_seen_at": now,
        "ct_val": _float_value(raw.get("ctVal"), _float_value(existing.get("ct_val"))),
        "lot_sz": _float_value(raw.get("lotSz"), _float_value(existing.get("lot_sz"))),
        "min_sz": _float_value(raw.get("minSz"), _float_value(existing.get("min_sz"))),
        "list_time": _int_value(raw.get("listTime"), existing.get("list_time")),
        "exp_time": _int_value(raw.get("expTime"), existing.get("exp_time")),
        "inst_family": raw.get("instFamily", existing.get("inst_family", "")),
        "uly": raw.get("uly", existing.get("uly", "")),
        "raw": raw,
    }
    if online:
        if not was_online:
            row["online_since"] = now
        else:
            row["online_since"] = existing.get("online_since") or now
        row["offline_since"] = None
    else:
        row["online_since"] = existing.get("online_since")
        row["offline_since"] = existing.get("offline_since") or now
    return row


def _mark_missing_offline(row: dict[str, Any], now: str) -> dict[str, Any]:
    updated = dict(row)
    if updated.get("is_online", False):
        updated["offline_since"] = updated.get("offline_since") or now
    updated["is_online"] = False
    updated["state"] = "missing_from_latest_snapshot"
    return updated


def filter_usdt_swap(raw_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in raw_rows
        if row.get("instType") == "SWAP" and row.get("settleCcy") == "USDT"
    ]


def merge_instrument_dim(
    existing_payload: dict[str, Any],
    raw_rows: Iterable[dict[str, Any]],
    *,
    now: str | None = None,
    source: str = "okx",
) -> tuple[dict[str, Any], dict[str, int]]:
    now = now or utc_now_iso()
    current_raw = filter_usdt_swap(raw_rows)
    existing_rows = {
        row.get("inst_id"): row
        for row in existing_payload.get("symbols", [])
        if row.get("inst_id")
    }
    current_ids = {row.get("instId") for row in current_raw if row.get("instId")}
    merged: dict[str, dict[str, Any]] = {}
    stats = {"new": 0, "online": 0, "offline": 0, "changed_state": 0, "missing": 0}

    for raw in current_raw:
        inst_id = raw.get("instId")
        if not inst_id:
            continue
        existing = existing_rows.get(inst_id)
        if existing is None:
            stats["new"] += 1
        elif existing.get("state") != raw.get("state", ""):
            stats["changed_state"] += 1
        row = _row_from_okx(raw, now, existing)
        merged[inst_id] = row

    for inst_id, row in existing_rows.items():
        if inst_id in current_ids:
            continue
        stats["missing"] += 1
        merged[inst_id] = _mark_missing_offline(row, now)

    rows = sorted(merged.values(), key=lambda item: item["inst_id"])
    stats["online"] = sum(1 for row in rows if row.get("is_online"))
    stats["offline"] = len(rows) - stats["online"]
    payload = {
        "meta": {
            "source": source,
            "updated_at": now,
            "description": "Ever-seen OKX USDT-settled SWAP instrument dimension.",
        },
        "summary": {
            "symbols": len(rows),
            "online": stats["online"],
            "offline": stats["offline"],
            "new": stats["new"],
            "changed_state": stats["changed_state"],
            "missing_from_latest_snapshot": stats["missing"],
        },
        "symbols": rows,
    }
    return payload, stats


def write_instrument_snapshot(path: Path | str, raw_rows: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "data": raw_rows}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def sync_instrument_dim(
    *,
    raw_rows: list[dict[str, Any]],
    dim_path: Path | str,
    snapshot_dir: Path | str | None = None,
    legacy_symbol_catalog: Path | str | None = None,
    now: str | None = None,
    source: str = "okx",
) -> tuple[dict[str, Any], dict[str, int]]:
    now = now or utc_now_iso()
    existing = load_instrument_dim(dim_path)
    payload, stats = merge_instrument_dim(existing, raw_rows, now=now, source=source)
    save_instrument_dim(dim_path, payload)

    if snapshot_dir is not None:
        date_key = date_key_from_iso(now)
        snapshot_path = Path(snapshot_dir) / f"date={date_key}" / "instruments_swap.json.gz"
        write_instrument_snapshot(snapshot_path, raw_rows, {"source": source, "fetched_at": now})

    if legacy_symbol_catalog is not None:
        online_rows = select_instrument_rows(payload, online_only=True, data_enabled_only=False)
        instruments = [
            Instrument(
                inst_id=row["inst_id"],
                inst_type=row.get("inst_type", "SWAP"),
                settle_ccy=row.get("settle_ccy", "USDT"),
                state=row.get("state", ""),
                ct_val=_float_value(row.get("ct_val")),
                lot_sz=_float_value(row.get("lot_sz")),
                min_sz=_float_value(row.get("min_sz")),
            )
            for row in online_rows
        ]
        write_symbol_catalog(legacy_symbol_catalog, instruments, {"source": "instrument_dim", "updated_at": now})

    return payload, stats


def select_instrument_rows(
    payload_or_path: dict[str, Any] | Path | str,
    *,
    online_only: bool = True,
    data_enabled_only: bool = True,
    backfill_enabled_only: bool = False,
) -> list[dict[str, Any]]:
    payload = load_instrument_dim(payload_or_path) if not isinstance(payload_or_path, dict) else payload_or_path
    rows = list(payload.get("symbols", []))
    if online_only:
        rows = [row for row in rows if row.get("is_online")]
    if data_enabled_only:
        rows = [row for row in rows if row.get("data_enabled", True)]
    if backfill_enabled_only:
        rows = [row for row in rows if row.get("backfill_enabled", True)]
    return sorted(rows, key=lambda item: item.get("inst_id", ""))


def select_instrument_symbols(
    payload_or_path: dict[str, Any] | Path | str,
    *,
    online_only: bool = True,
    data_enabled_only: bool = True,
    backfill_enabled_only: bool = False,
    limit: int | None = None,
) -> list[str]:
    rows = select_instrument_rows(
        payload_or_path,
        online_only=online_only,
        data_enabled_only=data_enabled_only,
        backfill_enabled_only=backfill_enabled_only,
    )
    symbols = [row["inst_id"] for row in rows if row.get("inst_id")]
    return symbols[:limit] if limit else symbols
