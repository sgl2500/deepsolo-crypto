from __future__ import annotations

import csv
import gzip
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from bisect import bisect_left

from .config import APP_TIMEZONE, TIMEFRAMES
from .data_source import data_source_service
from .indicator_repository import indicator_repository
from . import script_indicator_service


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    vol_quote: float
    raw: dict[str, str]


def query_screener(
    timeframe: str = "1m",
    date: str | None = None,
    as_of: str | None = None,
    min_ret_15m: float | None = None,
    min_vol_ratio_60: float | None = None,
    min_vol_quote_15m: float | None = None,
    sort_by: str = "ret_15m",
    sort_dir: str = "desc",
    metadata_filters: list[dict[str, Any]] | None = None,
    limit: int = 100,
    script_values_cache: dict[tuple[str, str, str], dict[str, list[dict[str, str]]]] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    selected_date = date or data_source_service.default_date(timeframe)
    if not selected_date:
        return _empty_response(timeframe, date, "No data partition found.")

    requested_date = selected_date
    as_of_ts = _parse_as_of(as_of)
    if as_of_ts is not None:
        selected_date = _partition_date_from_ts(timeframe, as_of_ts)
    files = data_source_service.contract_files(timeframe, selected_date)
    metadata_filter_specs = _prepare_metadata_filter_specs(metadata_filters or [], requested_date, as_of_ts)
    metadata_period_files = _metadata_period_files(metadata_filter_specs)
    metadata_script_values = _metadata_script_values(metadata_filter_specs, script_values_cache)
    rows: list[dict[str, Any]] = []
    condition_stats = {
        "min_ret_15m": 0,
        "min_vol_ratio_60": 0,
        "min_vol_quote_15m": 0,
    }
    latest_seen_ts: int | None = None

    for path in files:
        candles = _load_candles(path, as_of_ts)
        if not candles:
            continue

        metrics = _metrics(candles)
        if latest_seen_ts is None or metrics["latest_ts"] > latest_seen_ts:
            latest_seen_ts = metrics["latest_ts"]

        matched, reasons = _match(
            metrics,
            condition_stats,
            min_ret_15m=min_ret_15m,
            min_vol_ratio_60=min_vol_ratio_60,
            min_vol_quote_15m=min_vol_quote_15m,
        )
        if not matched:
            continue

        metadata_matched, metadata_reasons, metadata_values = _match_metadata_filters(
            path.name,
            timeframe,
            candles[-1].raw,
            condition_stats,
            metadata_filter_specs,
            metadata_period_files,
            metadata_script_values,
            as_of_ts,
        )
        if not metadata_matched:
            continue
        if metadata_reasons:
            if reasons == ["基础合约池"]:
                reasons = metadata_reasons
            else:
                reasons.extend(metadata_reasons)

        rows.append(
            {
                "inst_id": path.name.removesuffix(".csv.gz"),
                **metrics,
                "metadata_values": metadata_values,
                "matched_conditions": reasons,
            }
        )

    allowed_sort_keys = {
        "inst_id",
        "latest_close",
        "ret_15m",
        "ret_1h",
        "amp_15m",
        "vol_quote_15m",
        "vol_ratio_60",
        "latest_ts",
    }
    sort_key = sort_by if sort_by in allowed_sort_keys else "ret_15m"
    reverse = sort_dir.lower() != "asc"
    rows.sort(key=lambda item: _sort_value(item.get(sort_key)), reverse=reverse)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    limited_rows = rows[: max(1, min(limit, 500))]
    return {
        "timeframe": timeframe,
        "date": selected_date,
        "as_of_ts": latest_seen_ts if as_of_ts is None else as_of_ts,
        "as_of_label": _format_ts(latest_seen_ts if as_of_ts is None else as_of_ts),
        "total_contracts": len(files),
        "matched_count": len(rows),
        "returned_count": len(limited_rows),
        "duration_ms": elapsed_ms,
        "condition_stats": condition_stats,
        "columns": [
            "inst_id",
            "latest_close",
            "ret_15m",
            "ret_1h",
            "amp_15m",
            "vol_quote_15m",
            "vol_ratio_60",
            "latest_time",
            "matched_conditions",
        ],
        "rows": limited_rows,
    }


def query_screener_time_counts(
    timeframe: str = "1m",
    date: str | None = None,
    min_ret_15m: float | None = None,
    min_vol_ratio_60: float | None = None,
    min_vol_quote_15m: float | None = None,
    sort_by: str = "ret_15m",
    sort_dir: str = "desc",
    metadata_filters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    selected_date = date or data_source_service.default_date(timeframe)
    if not selected_date:
        return {
            "timeframe": timeframe,
            "date": date,
            "duration_ms": 0,
            "items": [],
            "message": "No data partition found.",
        }

    script_values_cache: dict[tuple[str, str, str], dict[str, list[dict[str, str]]]] = {}
    items: list[dict[str, Any]] = []
    for hour in _baseline_hours(timeframe):
        time_text = f"{hour:02d}:00"
        as_of = f"{selected_date}T{time_text}:00"
        result = query_screener(
            timeframe=timeframe,
            date=selected_date,
            as_of=as_of,
            min_ret_15m=min_ret_15m,
            min_vol_ratio_60=min_vol_ratio_60,
            min_vol_quote_15m=min_vol_quote_15m,
            sort_by=sort_by,
            sort_dir=sort_dir,
            metadata_filters=metadata_filters,
            limit=1,
            script_values_cache=script_values_cache,
        )
        items.append({
            "time": time_text,
            "as_of": as_of,
            "date": result.get("date"),
            "as_of_label": result.get("as_of_label"),
            "total_contracts": result.get("total_contracts", 0),
            "matched_count": result.get("matched_count", 0),
            "duration_ms": result.get("duration_ms", 0),
        })

    return {
        "timeframe": timeframe,
        "date": selected_date,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "items": items,
    }


def builtin_indicators() -> list[dict[str, str]]:
    return [
        {"key": "ret_15m", "name": "近15分钟涨幅", "unit": "%", "type": "number"},
        {"key": "ret_1h", "name": "近1小时涨幅", "unit": "%", "type": "number"},
        {"key": "amp_15m", "name": "近15分钟振幅", "unit": "%", "type": "number"},
        {
            "key": "vol_quote_15m",
            "name": "近15分钟成交额",
            "unit": "quote",
            "type": "number",
        },
        {
            "key": "vol_ratio_60",
            "name": "15分钟量能/近1小时均量",
            "unit": "x",
            "type": "number",
        },
    ]


def _empty_response(timeframe: str, date: str | None, message: str) -> dict[str, Any]:
    return {
        "timeframe": timeframe,
        "date": date,
        "as_of_ts": None,
        "as_of_label": None,
        "total_contracts": 0,
        "matched_count": 0,
        "returned_count": 0,
        "duration_ms": 0,
        "condition_stats": {},
        "columns": [],
        "rows": [],
        "message": message,
    }


def _load_candles(path: Path, as_of_ts: int | None) -> list[Candle]:
    candles: list[Candle] = []
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ts = _to_int(row.get("ts"))
            if ts is None:
                continue
            if as_of_ts is not None and ts > as_of_ts:
                break
            close = _to_float(row.get("close"))
            if close is None or close <= 0:
                continue
            candles.append(
                Candle(
                    ts=ts,
                    open=_to_float(row.get("open")) or close,
                    high=_to_float(row.get("high")) or close,
                    low=_to_float(row.get("low")) or close,
                    close=close,
                    vol_quote=_to_float(row.get("vol_ccy_quote")) or 0.0,
                    raw=row,
                )
            )
    return candles


def _metrics(candles: list[Candle]) -> dict[str, Any]:
    latest = candles[-1]
    last_15m = _window(candles, latest.ts - 15 * 60 * 1000)
    last_60m = _window(candles, latest.ts - 60 * 60 * 1000)

    base_15m = last_15m[0].close if last_15m else latest.open
    base_60m = last_60m[0].close if last_60m else latest.open

    vol_15m = sum(item.vol_quote for item in last_15m)
    vol_60m = sum(item.vol_quote for item in last_60m)
    avg_15m_from_60m = vol_60m / 4 if vol_60m > 0 else 0
    vol_ratio = vol_15m / avg_15m_from_60m if avg_15m_from_60m > 0 else 0

    high_15m = max((item.high for item in last_15m), default=latest.high)
    low_15m = min((item.low for item in last_15m), default=latest.low)

    return {
        "latest_ts": latest.ts,
        "latest_time": _format_ts(latest.ts),
        "latest_close": _round(latest.close, 8),
        "ret_15m": _round(_pct(latest.close, base_15m), 4),
        "ret_1h": _round(_pct(latest.close, base_60m), 4),
        "amp_15m": _round(_pct(high_15m, low_15m), 4),
        "vol_quote_15m": _round(vol_15m, 4),
        "vol_ratio_60": _round(vol_ratio, 4),
    }


def _window(candles: list[Candle], start_ts: int) -> list[Candle]:
    return [item for item in candles if item.ts >= start_ts]


def _match(
    metrics: dict[str, Any],
    condition_stats: dict[str, int],
    *,
    min_ret_15m: float | None,
    min_vol_ratio_60: float | None,
    min_vol_quote_15m: float | None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if min_ret_15m is not None:
        if metrics["ret_15m"] < min_ret_15m:
            return False, []
        condition_stats["min_ret_15m"] += 1
        reasons.append(f"近15分钟涨幅 >= {min_ret_15m:g}%")

    if min_vol_ratio_60 is not None:
        if metrics["vol_ratio_60"] < min_vol_ratio_60:
            return False, []
        condition_stats["min_vol_ratio_60"] += 1
        reasons.append(f"量能倍数 >= {min_vol_ratio_60:g}x")

    if min_vol_quote_15m is not None:
        if metrics["vol_quote_15m"] < min_vol_quote_15m:
            return False, []
        condition_stats["min_vol_quote_15m"] += 1
        reasons.append(f"15分钟成交额 >= {min_vol_quote_15m:g}")

    if not reasons:
        reasons.append("基础合约池")
    return True, reasons


def _match_metadata_filters(
    file_name: str,
    base_timeframe: str,
    raw_row: dict[str, str],
    condition_stats: dict[str, int],
    filters: list[dict[str, Any]],
    period_files: dict[tuple[str, str], dict[str, Path]],
    script_values: dict[tuple[str, str], dict[str, list[dict[str, str]]]],
    as_of_ts: int | None,
) -> tuple[bool, list[str], dict[str, str]]:
    if not filters:
        return True, [], {}

    reasons: list[str] = []
    values: dict[str, str] = {}
    all_passed = True
    for index, condition in enumerate(filters, start=1):
        indicator_id = str(condition.get("indicator_id") or "")
        indicator = condition.get("_indicator")
        stat_key = f"metadata_{index}_{indicator_id}"
        condition_stats.setdefault(stat_key, 0)

        if not indicator:
            all_passed = False
            continue

        indicator_period = str(indicator.get("storage_period") or base_timeframe)
        target_date = str(condition.get("_target_date") or "")
        condition_as_of_ts = condition.get("_condition_as_of_ts")
        if condition_as_of_ts is None:
            condition_as_of_ts = _condition_as_of_ts(condition, target_date, indicator_period, as_of_ts)
        operator = str(condition.get("operator") or "gt")
        expected = str(condition.get("value") or "")
        value_mode = _value_mode(operator)
        raw_value: str | None = None

        if indicator.get("source_type") == "script":
            inst_id = file_name.removesuffix(".csv.gz")
            source_row = _latest_script_row(
                script_values.get((indicator_id, target_date), {}),
                inst_id,
                condition_as_of_ts,
            )
            if source_row is not None and condition.get("match_current_bar", True):
                source_ts = _to_int(source_row.get("ts"))
                target_ts = condition_as_of_ts
                if target_ts is None and _period_step_minutes(indicator_period) is not None:
                    target_ts = as_of_ts
                if target_ts is not None and source_ts != target_ts:
                    source_row = None
            if source_row is None:
                if value_mode == "any":
                    pass
                elif value_mode == "empty":
                    condition_stats[stat_key] += 1
                    reasons.append(_metadata_reason(indicator, operator, expected, False))
                    continue
                else:
                    all_passed = False
                continue
            raw_value = source_row.get("value", "") or ""
            source_ts = source_row.get("ts", "") or ""
            if source_ts:
                values[f"{indicator_id}::ts"] = source_ts
        else:
            raw_field = indicator.get("raw_field")
            if not raw_field:
                if value_mode == "empty":
                    condition_stats[stat_key] += 1
                    reasons.append(_metadata_reason(indicator, operator, expected, False))
                    continue
                if value_mode != "any":
                    all_passed = False
                continue

            source_row = raw_row
            if indicator_period.lower() != base_timeframe.lower() or target_date:
                source_key = (indicator_period, target_date)
                source_path = period_files.get(source_key, {}).get(file_name)
                if source_path is None:
                    if value_mode == "empty":
                        condition_stats[stat_key] += 1
                        reasons.append(_metadata_reason(indicator, operator, expected, False))
                        continue
                    if value_mode != "any":
                        all_passed = False
                    continue
                source_row = _latest_raw_row(source_path, condition_as_of_ts)
                if source_row is None:
                    if value_mode == "empty":
                        condition_stats[stat_key] += 1
                        reasons.append(_metadata_reason(indicator, operator, expected, False))
                        continue
                    if value_mode != "any":
                        all_passed = False
                    continue
            raw_value = source_row.get(raw_field, "") or ""

        value_key = _metadata_value_key(indicator_id, target_date, _condition_time_point_key(condition, indicator_period))
        values[value_key] = raw_value
        values[indicator_id] = raw_value
        if value_mode == "any":
            passed = True
        elif value_mode == "empty":
            passed = raw_value.strip() == ""
        elif value_mode == "not_empty":
            passed = raw_value.strip() != ""
        else:
            passed = _compare_metadata_value(
                raw_value,
                expected,
                operator,
                str(indicator.get("data_type") or "string"),
            )

        if condition.get("exclude") and value_mode == "filter":
            passed = not passed

        if not passed:
            all_passed = False
            continue

        if value_mode in ("empty", "not_empty") or raw_value not in (None, ""):
            condition_stats[stat_key] += 1
        if value_mode != "any":
            reasons.append(_metadata_reason(indicator, operator, expected, bool(condition.get("exclude"))))

    if not all_passed:
        return False, [], {}

    return True, reasons, values


def _prepare_metadata_filter_specs(
    filters: list[dict[str, Any]],
    selected_date: str,
    as_of_ts: int | None,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for condition in filters:
        indicator_id = str(condition.get("indicator_id") or "")
        indicator = indicator_repository.get(indicator_id)
        target_date = ""
        condition_as_of_ts = None
        if indicator:
            indicator_period = str(indicator.get("storage_period"))
            target_local_date = _condition_target_local_date(condition, indicator_period, selected_date, as_of_ts)
            condition_as_of_ts = _condition_as_of_ts(condition, target_local_date, indicator_period, as_of_ts)
            target_date = target_local_date
            if condition_as_of_ts is not None and _period_step_minutes(indicator_period) is not None:
                target_date = _partition_date_from_ts(indicator_period, condition_as_of_ts)
        specs.append({
            **condition,
            "_indicator": indicator,
            "_target_date": target_date,
            "_condition_as_of_ts": condition_as_of_ts,
        })
    return specs


def _metadata_period_files(filters: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Path]]:
    period_dates = {
        (str(indicator.get("storage_period")), str(condition.get("_target_date")))
        for condition in filters
        if (indicator := condition.get("_indicator"))
        and indicator.get("source_type") != "script"
        and indicator.get("storage_period")
        and condition.get("_target_date")
    }
    return {
        (period, date): {path.name: path for path in data_source_service.contract_files(period, date)}
        for period, date in period_dates
    }


def _metadata_script_values(
    filters: list[dict[str, Any]],
    cache: dict[tuple[str, str, str], dict[str, list[dict[str, str]]]] | None = None,
) -> dict[tuple[str, str], dict[str, list[dict[str, str]]]]:
    outputs: dict[tuple[str, str], dict[str, list[dict[str, str]]]] = {}
    script_conditions = [
        condition
        for condition in filters
        if (indicator := condition.get("_indicator")) and indicator.get("source_type") == "script"
    ]
    for condition in script_conditions:
        indicator = condition["_indicator"]
        indicator_id = str(indicator.get("id"))
        target_date = str(condition.get("_target_date") or "")
        input_timeframe = str(indicator.get("storage_period") or "1m")
        key = (indicator_id, target_date)
        if key in outputs:
            continue
        cache_key = (indicator_id, target_date, input_timeframe)
        if cache is not None and cache_key in cache:
            outputs[key] = cache[cache_key]
            continue

        result = script_indicator_service.trial_run(
            indicator_id,
            date=target_date,
            input_timeframe=input_timeframe,
            limit=200_000,
        )
        if result.get("timed_out"):
            detail = result.get("stderr") or "脚本指标运行超时"
            raise TimeoutError(f"{indicator.get('name_zh') or indicator_id}：{detail}")
        if not result.get("success"):
            detail = result.get("stderr") or "脚本执行失败，无法参与组合查询"
            raise ValueError(f"{indicator.get('name_zh') or indicator_id}：{detail}")
        grouped_rows = _group_script_rows(result.get("rows", []))
        if cache is not None:
            cache[cache_key] = grouped_rows
        outputs[key] = grouped_rows
    return outputs


def _group_script_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        inst_id = str(row.get("inst_id") or "")
        if not inst_id:
            continue
        grouped.setdefault(inst_id, []).append(row)
    for values in grouped.values():
        values.sort(key=lambda item: _to_int(item.get("ts")) or -1)
    return grouped


def _latest_script_row(
    rows_by_inst: dict[str, list[dict[str, str]]],
    inst_id: str,
    as_of_ts: int | None,
) -> dict[str, str] | None:
    selected: dict[str, str] | None = None
    for row in rows_by_inst.get(inst_id, []):
        ts = _to_int(row.get("ts"))
        if as_of_ts is not None and ts is not None and ts > as_of_ts:
            break
        selected = row
    return selected


def _condition_target_local_date(
    condition: dict[str, Any],
    period: str,
    selected_date: str,
    as_of_ts: int | None,
) -> str:
    reference_date = _local_date_from_ts(as_of_ts) if as_of_ts is not None else selected_date
    if condition.get("time_mode") != "previous_trading_day":
        if _period_step_minutes(period) is None and as_of_ts is not None:
            # At an intraday global baseline, a 1D condition can only see the
            # previous completed daily candle; the current daily candle is not final.
            return _available_date_offset_before(period, reference_date, 1) or _date_offset(reference_date, -1)
        return reference_date

    offset = _positive_int(condition.get("time_offset"), default=1)
    return _available_date_offset_before(period, reference_date, offset) or _date_offset(reference_date, -offset)


def _condition_as_of_ts(
    condition: dict[str, Any],
    target_date: str,
    indicator_period: str,
    fallback_as_of_ts: int | None,
) -> int | None:
    if _period_step_minutes(indicator_period) is None:
        return None

    mode = _condition_time_point_mode(condition)
    time_point = str(condition.get("time_point") or "").strip()
    if mode == "fixed" and time_point:
        return _parse_time_point(target_date, time_point, indicator_period)

    if fallback_as_of_ts is None:
        return None
    baseline_ts = _same_local_time_on_date(target_date, fallback_as_of_ts) if target_date else fallback_as_of_ts

    if mode == "bar_offset":
        offset = _non_negative_int(condition.get("bar_offset"), default=0)
        step = _period_step_minutes(indicator_period) or 1
        return baseline_ts - offset * step * 60_000

    if mode == "time_offset":
        offset = _non_negative_int(condition.get("time_offset_value"), default=0)
        unit = str(condition.get("time_offset_unit") or "hour").strip().lower()
        unit_minutes = 1 if unit in ("minute", "minutes", "m", "分钟") else 60
        return baseline_ts - offset * unit_minutes * 60_000

    return baseline_ts


def _parse_time_point(date: str, time_point: str, indicator_period: str) -> int:
    step = _period_step_minutes(indicator_period)
    normalized = time_point.strip()
    if not normalized:
        raise ValueError("筛选条件的 K线时刻不能为空")
    if step is None:
        raise ValueError(f"{indicator_period} 周期只能指定交易日，不能指定 K线时刻")
    if len(normalized) == 5:
        normalized = f"{normalized}:00"
    dt = datetime.fromisoformat(f"{date}T{normalized}")
    dt = dt.replace(tzinfo=ZoneInfo(APP_TIMEZONE))
    if dt.second != 0:
        raise ValueError("筛选条件的 K线时刻只能精确到分钟")
    total_minutes = dt.hour * 60 + dt.minute
    if total_minutes % step != 0:
        raise ValueError(f"{indicator_period} 周期的 K线时刻必须是 {step} 分钟整数倍")
    return int(dt.timestamp() * 1000)


def _metadata_value_key(indicator_id: str, target_date: str, time_point_key: str) -> str:
    normalized_time = time_point_key.strip() or "latest"
    return f"{indicator_id}::{target_date}::{normalized_time}"


def _condition_time_point_mode(condition: dict[str, Any]) -> str:
    mode = str(condition.get("time_point_mode") or "").strip().lower()
    if mode in {"baseline", "bar_offset", "time_offset", "fixed"}:
        return mode
    if str(condition.get("time_point") or "").strip():
        return "fixed"
    return "baseline"


def _condition_time_point_key(condition: dict[str, Any], indicator_period: str) -> str:
    if _period_step_minutes(indicator_period) is None:
        return "latest"
    mode = _condition_time_point_mode(condition)
    if mode == "fixed":
        return str(condition.get("time_point") or "").strip() or "latest"
    if mode == "bar_offset":
        offset = _non_negative_int(condition.get("bar_offset"), default=0)
        return "latest" if offset == 0 else f"bar_offset:{offset}"
    if mode == "time_offset":
        offset = _non_negative_int(condition.get("time_offset_value"), default=0)
        unit = str(condition.get("time_offset_unit") or "hour").strip().lower()
        unit_key = "minute" if unit in ("minute", "minutes", "m", "分钟") else "hour"
        return "latest" if offset == 0 else f"time_offset:{offset}{unit_key}"
    return "latest"


def _period_step_minutes(period: str) -> int | None:
    normalized = period.strip().lower()
    unit = normalized[-1:] if normalized else ""
    try:
        count = int(normalized[:-1])
    except ValueError:
        return 1
    if count <= 0:
        return 1
    if unit == "m":
        return count
    if unit == "h":
        return count * 60
    if unit == "d":
        return None
    return 1


def _baseline_hours(period: str) -> list[int]:
    if _period_step_minutes(period) is None:
        return [0]
    return list(range(24))


def _available_dates(period: str) -> list[str]:
    timeframe_key = next((key for key in TIMEFRAMES if key.lower() == period.lower()), None)
    if not timeframe_key:
        return []
    tf_dir = data_source_service.root / TIMEFRAMES[timeframe_key]
    if not tf_dir.exists():
        return []

    dates: list[str] = []
    for entry in tf_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("date="):
            dates.append(entry.name.split("date=", 1)[1])
    return sorted(dates)


def _available_date_before(period: str, reference_date: str) -> str | None:
    return _available_date_offset_before(period, reference_date, 1)


def _available_date_offset_before(period: str, reference_date: str, offset: int) -> str | None:
    dates = _available_dates(period)
    if not dates:
        return None
    safe_offset = max(1, offset)
    target_index = bisect_left(dates, reference_date) - safe_offset
    if target_index < 0:
        return dates[0]
    return dates[target_index]


def _local_date_from_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=ZoneInfo(APP_TIMEZONE)).date().isoformat()


def _date_offset(value: str, days: int) -> str:
    try:
        current = datetime.fromisoformat(value)
    except ValueError:
        return value
    return (current + timedelta(days=days)).date().isoformat()


def _partition_date_from_ts(period: str, ts: int) -> str:
    if _period_step_minutes(period) is None:
        dt = datetime.fromtimestamp(ts / 1000, tz=ZoneInfo(APP_TIMEZONE))
    else:
        # Intraday folders use UTC date partitions: CST 08:00 to next-day 07:59.
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return dt.date().isoformat()


def _same_local_time_on_date(target_date: str, source_ts: int) -> int:
    source_dt = datetime.fromtimestamp(source_ts / 1000, tz=ZoneInfo(APP_TIMEZONE))
    target_dt = datetime.fromisoformat(f"{target_date}T{source_dt.strftime('%H:%M:%S')}")
    target_dt = target_dt.replace(tzinfo=ZoneInfo(APP_TIMEZONE))
    return int(target_dt.timestamp() * 1000)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _latest_raw_row(path: Path, as_of_ts: int | None) -> dict[str, str] | None:
    selected: dict[str, str] | None = None
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ts = _to_int(row.get("ts"))
            if ts is None:
                continue
            if as_of_ts is not None and ts > as_of_ts:
                break
            selected = row
    return selected


def _value_mode(operator: str) -> str:
    normalized = operator.strip().lower()
    if normalized in ("any", "*", "任意"):
        return "any"
    if normalized in ("any_empty", "empty", "is_empty", "blank", "任意为空", "为空"):
        return "empty"
    if normalized in ("any_not_empty", "not_empty", "is_not_empty", "not_blank", "任意不为空", "不为空"):
        return "not_empty"
    return "filter"


def _compare_metadata_value(raw_value: str, expected: str, operator: str, data_type: str) -> bool:
    if _value_mode(operator) == "any":
        return True

    if data_type == "number":
        current_number = _to_float(raw_value)
        expected_number = _to_float(expected)
        if current_number is None or expected_number is None:
            return False
        return _compare_ordered(current_number, expected_number, operator)

    if data_type == "boolean":
        current_bool = raw_value in ("1", "true", "True", "TRUE")
        expected_bool = expected in ("1", "true", "True", "TRUE", "是")
        if operator in ("ne", "!="):
            return current_bool != expected_bool
        return current_bool == expected_bool

    normalized_current = raw_value.strip()
    normalized_expected = expected.strip()
    if operator in ("contains", "include"):
        return normalized_expected.lower() in normalized_current.lower()
    if operator in ("ne", "!="):
        return normalized_current != normalized_expected
    return normalized_current == normalized_expected


def _compare_ordered(current: float, expected: float, operator: str) -> bool:
    if operator in ("gt", ">"):
        return current > expected
    if operator in ("gte", ">="):
        return current >= expected
    if operator in ("lt", "<"):
        return current < expected
    if operator in ("lte", "<="):
        return current <= expected
    if operator in ("ne", "!="):
        return current != expected
    return current == expected


def _metadata_reason(indicator: dict[str, Any], operator: str, expected: str, excluded: bool) -> str:
    labels = {
        "any": "任意",
        "any_empty": "为空",
        "any_not_empty": "不为空",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "eq": "=",
        "ne": "!=",
        "contains": "包含",
    }
    label = labels.get(operator, operator)
    prefix = "排除：" if excluded else ""
    unit = indicator.get("unit") or ""
    return f"{prefix}{indicator.get('name_zh', indicator.get('id'))} {label} {expected}{unit}"


def _pct(new_value: float, old_value: float) -> float:
    if old_value == 0:
        return 0.0
    return (new_value - old_value) / old_value * 100


def _round(value: float, digits: int) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(value, digits)


def _sort_value(value: Any) -> Any:
    if value is None:
        return -float("inf")
    return value


def _to_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _parse_as_of(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)

    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(APP_TIMEZONE))
    return int(dt.timestamp() * 1000)


def _format_ts(ts: int | None) -> str | None:
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts / 1000, tz=ZoneInfo(APP_TIMEZONE))
    return dt.strftime("%Y-%m-%d %H:%M")
